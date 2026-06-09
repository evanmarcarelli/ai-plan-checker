"""Code corpus loader + BM25 retriever.

Why BM25 and not vector embeddings?
- Building code language is highly lexical ("Group R-3", "minimum 44 inches",
  "Class A roof"). BM25 nails this without an embedding API call.
- Zero extra API keys; runs in-process; ~1ms per query.
- The corpus is the moat, not the embedding model. Vector embeddings can be
  layered on later via the `Retriever` interface without touching agents.

Corpus format (JSONL files in corpus/):
    {
      "code_name": "ADA 2010 Standards for Accessible Design",
      "code_short": "ADA",
      "version": "2010",
      "section": "404.2.3",
      "title": "Clear Width",
      "category": "accessibility",
      "jurisdictions": ["*"],     // "*" = federal/national, or ["CA"], ["CA:Altadena"]
      "text": "Door openings shall provide a clear width of 32 inches (815 mm) minimum...",
      "tags": ["door", "egress", "accessible route"]
    }

Each line of each .jsonl file is one chunk.
"""
from __future__ import annotations

import json
import re
import threading
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

from pydantic import BaseModel
from rank_bm25 import BM25Okapi

from app.utils.logger import get_logger

logger = get_logger(__name__)

CORPUS_DIR = Path(__file__).parent / "corpus"


# ---------- Schema ----------

class CodeChunk(BaseModel):
    """A single, citable chunk of code text."""
    chunk_id: str
    code_name: str
    code_short: str          # e.g. "ADA", "IBC", "T24", "CALGREEN"
    version: str
    section: str             # e.g. "404.2.3"
    title: str = ""
    category: str            # building_safety, fire, electrical, plumbing, mechanical,
                             # accessibility, energy, zoning, public_works, environmental
    jurisdictions: List[str] = []   # ["*"] or ["CA"] or ["CA:Altadena"]
    text: str
    tags: List[str] = []

    # ── structured fields (migration 008) — all optional, so existing JSONL
    #    loads unchanged. Populated when loading from Postgres or after the
    #    structured ingest backfills them. ──
    path: Optional[str] = None            # ltree path, e.g. "c10.s1004.s1004_1"
    adoption_id: Optional[str] = None     # jurisdiction scope key (None = base)
    parent_section: Optional[str] = None  # "1004.1" for "1004.1.1"
    context_header: Optional[str] = None  # breadcrumb for retrieval/grounding
    source_tier: str = "unspecified"      # provenance: official_gov|licensed|...
    license_status: str = "review"        # edict|licensed|fair_use_review|review

    @property
    def citation(self) -> str:
        """Canonical citation string e.g. 'ADA 404.2.3'."""
        return f"{self.code_short} {self.section}"

    def applies_to(self, state: Optional[str], city: Optional[str]) -> bool:
        """Return True iff this chunk applies to the given jurisdiction."""
        if not self.jurisdictions or "*" in self.jurisdictions:
            return True
        if not state:
            return False
        state_u = state.upper()
        for j in self.jurisdictions:
            if j.upper() == state_u:
                return True
            if ":" in j:
                jstate, jcity = j.split(":", 1)
                if jstate.upper() == state_u and city and jcity.lower() in city.lower():
                    return True
        return False

    def in_layers(self, layer_keys: Sequence[str]) -> bool:
        """Return True iff this chunk belongs to one of the resolved corpus
        layer keys (from the adoption resolver, e.g. ['*','CA','CA:Los Angeles']).

        This is the authoritative jurisdiction test: the resolver decides which
        layers apply to a jurisdiction (handling county, inheritance, address
        geocoding), and a chunk applies iff its own tag is one of them. A base
        chunk ('*') always applies."""
        if "*" in self.jurisdictions:
            return True
        keys = set(layer_keys)
        return any(j in keys for j in self.jurisdictions)


# ---------- Tokenizer ----------

_TOKEN_RE = re.compile(r"[a-z0-9]+(?:[./-][a-z0-9]+)*", re.IGNORECASE)
_STOPWORDS = {
    "the", "a", "an", "of", "to", "in", "on", "for", "and", "or", "with", "by",
    "shall", "be", "is", "are", "as", "at", "from", "that", "this", "which",
}


def tokenize(text: str) -> List[str]:
    """BM25 tokenizer: lowercase, keep section-number-like tokens intact."""
    return [t.lower() for t in _TOKEN_RE.findall(text) if t.lower() not in _STOPWORDS]


# ---------- Corpus + Retriever ----------

class CodeCorpus:
    def __init__(self) -> None:
        self.chunks: List[CodeChunk] = []
        self.by_citation: Dict[str, CodeChunk] = {}
        self.by_section: Dict[str, CodeChunk] = {}

    def add(self, chunk: CodeChunk) -> None:
        self.chunks.append(chunk)
        self.by_citation[chunk.citation.lower()] = chunk
        # Also index by section alone (so "404.2.3" finds it even without code prefix)
        self.by_section.setdefault(chunk.section.lower(), chunk)

    def has_section(self, citation_or_section: str) -> bool:
        """Verify a citation string actually exists in the corpus."""
        if not citation_or_section:
            return False
        key = citation_or_section.strip().lower()
        if key in self.by_citation:
            return True
        # Normalize "ADA-404.2.3" → "ada 404.2.3"
        normalized = key.replace("-", " ").replace("_", " ")
        if normalized in self.by_citation:
            return True
        # Last resort: just the section number
        m = re.search(r"\d+[a-z]?(?:\.\d+[a-z]?)*", key)
        if m and m.group(0) in self.by_section:
            return True
        return False

    def get(self, citation_or_section: str) -> Optional[CodeChunk]:
        key = citation_or_section.strip().lower()
        if key in self.by_citation:
            return self.by_citation[key]
        normalized = key.replace("-", " ").replace("_", " ")
        if normalized in self.by_citation:
            return self.by_citation[normalized]
        m = re.search(r"\d+[a-z]?(?:\.\d+[a-z]?)*", key)
        if m and m.group(0) in self.by_section:
            return self.by_section[m.group(0)]
        return None


class CodeRetriever:
    """BM25 retriever with optional category + jurisdiction filters."""

    def __init__(self, corpus: CodeCorpus):
        self.corpus = corpus
        self._tokenized = [tokenize(f"{c.title} {c.text} {' '.join(c.tags)}") for c in corpus.chunks]
        self._bm25 = BM25Okapi(self._tokenized) if self._tokenized else None

    def search(
        self,
        query: str,
        *,
        category: Optional[str] = None,
        state: Optional[str] = None,
        city: Optional[str] = None,
        layer_keys: Optional[Sequence[str]] = None,
        adoption_id: Optional[str] = None,
        k: int = 6,
        min_score: float = 0.5,
    ) -> List[CodeChunk]:
        if not self._bm25 or not self.corpus.chunks:
            return []
        scores = self._bm25.get_scores(tokenize(query))
        # Pair (chunk, score), apply filters
        scored: List[tuple] = []
        for chunk, score in zip(self.corpus.chunks, scores):
            if category and chunk.category != category:
                continue
            # Jurisdiction scope, in priority order:
            #  1. layer_keys  — authoritative set from the adoption resolver
            #     (the production path; e.g. ['*','CA','CA:Los Angeles']).
            #  2. adoption_id — structured Postgres scope (migration 008).
            #  3. applies_to  — legacy fuzzy geo match (no jurisdiction given).
            if layer_keys is not None:
                if not chunk.in_layers(layer_keys):
                    continue
            elif adoption_id is not None:
                if chunk.adoption_id not in (adoption_id, None):
                    continue
            elif not chunk.applies_to(state, city):
                continue
            if score < min_score:
                continue
            scored.append((chunk, float(score)))
        scored.sort(key=lambda t: t[1], reverse=True)
        return [c for c, _ in scored[:k]]

    def all_for_category(
        self,
        category: str,
        *,
        state: Optional[str] = None,
        city: Optional[str] = None,
        layer_keys: Optional[Sequence[str]] = None,
        limit: Optional[int] = None,
    ) -> List[CodeChunk]:
        """Return every chunk in a category, jurisdiction-filtered. Used by department
        agents as the baseline 'must check' list (RAG augments, doesn't replace).

        Prefers the resolver's layer_keys (authoritative); falls back to the
        legacy applies_to() geo match when no layers are supplied."""
        def _applies(c: CodeChunk) -> bool:
            return c.in_layers(layer_keys) if layer_keys is not None else c.applies_to(state, city)
        result = [c for c in self.corpus.chunks if c.category == category and _applies(c)]
        return result[:limit] if limit else result


# ---------- Loading + singletons ----------

def _load_corpus_from_disk() -> CodeCorpus:
    """Read every *.jsonl in corpus/ and build a CodeCorpus."""
    corpus = CodeCorpus()
    if not CORPUS_DIR.exists():
        logger.warning(f"[code_library] corpus dir missing: {CORPUS_DIR}")
        return corpus

    files = sorted(CORPUS_DIR.glob("*.jsonl"))
    if not files:
        logger.warning(f"[code_library] no .jsonl corpus files in {CORPUS_DIR}")
        return corpus

    for fp in files:
        count_before = len(corpus.chunks)
        try:
            with fp.open(encoding="utf-8") as f:
                for lineno, line in enumerate(f, 1):
                    line = line.strip()
                    if not line or line.startswith("//"):
                        continue
                    try:
                        raw = json.loads(line)
                    except json.JSONDecodeError as e:
                        logger.error(f"[code_library] {fp.name}:{lineno} bad JSON: {e}")
                        continue
                    # Derive chunk_id if not provided
                    raw.setdefault(
                        "chunk_id",
                        f"{raw.get('code_short','?')}-{raw.get('section','?')}".lower(),
                    )
                    try:
                        corpus.add(CodeChunk(**raw))
                    except Exception as e:
                        logger.error(f"[code_library] {fp.name}:{lineno} bad chunk: {e}")
        except Exception as e:
            logger.error(f"[code_library] failed to load {fp}: {e}")
        logger.info(f"[code_library] loaded {len(corpus.chunks)-count_before} chunks from {fp.name}")

    logger.info(f"[code_library] corpus ready: {len(corpus.chunks)} total chunks")
    return corpus


def _load_corpus_from_postgres() -> CodeCorpus:
    """Build a CodeCorpus from the Postgres code_chunks table (migration 008).

    Maps each DB row back onto the same CodeChunk shape, so the BM25 retriever
    and every downstream caller work identically — the only change is that the
    corpus now lives in the database (single source of truth, provenance,
    hybrid-search ready) instead of on-disk JSONL."""
    from app.code_library import store

    corpus = CodeCorpus()
    rows = store.fetch_all_chunks()
    for r in rows:
        try:
            corpus.add(CodeChunk(
                chunk_id=r["chunk_id"],
                code_name=r.get("code_short", "") or "",
                code_short=r.get("code_short", "") or "",
                version=r.get("version", "") or "",
                section=r.get("section", "") or "",
                title=r.get("heading") or "",
                category=r.get("discipline", "") or "",
                jurisdictions=r.get("jurisdictions") or [],
                text=r.get("body", "") or "",
                tags=r.get("tags") or [],
                path=r.get("path"),
                adoption_id=r.get("adoption_id"),
                parent_section=r.get("parent_section"),
                context_header=r.get("context_header"),
                source_tier=r.get("source_tier") or "unspecified",
                license_status=r.get("license_status") or "review",
            ))
        except Exception as e:
            logger.error(f"[code_library] bad PG chunk {r.get('chunk_id')}: {e}")
    logger.info(f"[code_library] corpus ready (postgres): {len(corpus.chunks)} chunks")
    return corpus


def _load_corpus() -> CodeCorpus:
    """Choose the corpus source. CODE_STORE=postgres uses the DB when it's
    populated (migration 008 + ingest run), otherwise falls back to disk JSONL.
    Default is disk, so this change is a no-op until explicitly switched on."""
    try:
        from app.config import settings
        prefer_pg = getattr(settings, "code_store", "disk").lower() == "postgres"
    except Exception:
        prefer_pg = False

    if prefer_pg:
        try:
            from app.code_library import store
            if store.corpus_in_postgres():
                return _load_corpus_from_postgres()
            logger.warning("[code_library] CODE_STORE=postgres but code_chunks is "
                           "empty/missing — falling back to disk JSONL")
        except Exception as e:
            logger.warning(f"[code_library] postgres corpus load failed, using disk: {e}")
    return _load_corpus_from_disk()


_corpus_lock = threading.RLock()
_corpus_singleton: Optional[CodeCorpus] = None
_retriever_singleton: Optional[CodeRetriever] = None


def get_corpus() -> CodeCorpus:
    global _corpus_singleton
    with _corpus_lock:
        if _corpus_singleton is None:
            _corpus_singleton = _load_corpus()
        return _corpus_singleton


def get_retriever() -> CodeRetriever:
    global _retriever_singleton
    with _corpus_lock:
        if _retriever_singleton is None:
            _retriever_singleton = CodeRetriever(get_corpus())
        return _retriever_singleton


def reload_corpus() -> CodeCorpus:
    """Force a reload (from the configured source) — useful in tests and after
    ingesting new data."""
    global _corpus_singleton, _retriever_singleton
    with _corpus_lock:
        _corpus_singleton = _load_corpus()
        _retriever_singleton = CodeRetriever(_corpus_singleton)
        return _corpus_singleton
