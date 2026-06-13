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
        # All chunks sharing a bare section number. Section numbers collide
        # across codes (IBC, CEBC, CBC, CRC all have a "506.2"), so a single
        # by_section entry can't answer a code-prefixed citation correctly —
        # the prefixed fallback searches this list for the matching code.
        self.by_section_all: Dict[str, List[CodeChunk]] = {}

    def add(self, chunk: CodeChunk) -> None:
        self.chunks.append(chunk)
        self.by_citation[chunk.citation.lower()] = chunk
        # Also index by section alone (so "404.2.3" finds it even without code prefix)
        sec = chunk.section.lower()
        self.by_section.setdefault(sec, chunk)
        self.by_section_all.setdefault(sec, []).append(chunk)

    @staticmethod
    def _code_prefix(key: str) -> Optional[str]:
        """The code token a citation starts with ('cbc 404.2.3' -> 'cbc'),
        or None when the string is a bare section number."""
        m = re.match(r"\s*([a-z][a-z0-9&]*)", key)
        return m.group(1) if m else None

    def _section_fallback(self, key: str) -> Optional[CodeChunk]:
        """Bare-section lookup, guarded against cross-code matches.

        'CBC 404.2.3' must NOT resolve to ADA 404.2.3 just because ADA loads
        first and owns the bare number — a citation to a code we don't have
        must fail closed (UNVERIFIED), not get 'verified' against an unrelated
        code's text. The fallback only fires when the query has no code prefix
        at all, or its prefix matches the found chunk's code_short.
        """
        m = re.search(r"\d+[a-z]?(?:\.\d+[a-z]?)*", key)
        if not m:
            return None
        candidates = self.by_section_all.get(m.group(0))
        if not candidates:
            return None
        prefix = self._code_prefix(key)
        if prefix is None:
            # Bare section number, no code named: any code that has it answers.
            return candidates[0]
        # Code-prefixed citation: only a chunk from THAT code verifies it, even
        # when several codes share the bare number. "table"/"section" lead-ins
        # ("IBC Table 506.2") aren't code tokens, so a prefix that matches no
        # candidate's code_short falls back to matching any (the bare number is
        # still real) rather than failing closed on the lead-in word.
        for c in candidates:
            short = c.code_short.lower()
            if prefix in short or short in prefix:
                return c
        if prefix in {"table", "section", "sections", "chapter", "appendix", "figure"}:
            return candidates[0]
        return None

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
        return self._section_fallback(normalized) is not None

    def get(self, citation_or_section: str) -> Optional[CodeChunk]:
        key = citation_or_section.strip().lower()
        if key in self.by_citation:
            return self.by_citation[key]
        normalized = key.replace("-", " ").replace("_", " ")
        if normalized in self.by_citation:
            return self.by_citation[normalized]
        return self._section_fallback(normalized)


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
            #  1. layer_keys  — authoritative set from the adoption resolver. FALL
            #     OPEN: in_layers OR applies_to, so resolver hiccups / unmapped
            #     jurisdictions never DROP a code (a missed code is the liability).
            #  2. adoption_id — structured Postgres scope (migration 008).
            #  3. applies_to  — legacy fuzzy geo match (no jurisdiction given).
            if layer_keys is not None:
                if not (chunk.in_layers(layer_keys) or chunk.applies_to(state, city)):
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

        Uses the resolver's layer_keys when supplied, but FALLS OPEN (layers OR
        applies_to) so a degraded scope never drops a code; falls back to the
        legacy applies_to() geo match when no layers are supplied."""
        def _applies(c: CodeChunk) -> bool:
            if layer_keys is not None:
                return c.in_layers(layer_keys) or c.applies_to(state, city)
            return c.applies_to(state, city)
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


_corpus_source: Optional[str] = None   # "disk" | "postgres" — what actually loaded


def get_corpus_source() -> Optional[str]:
    """The source the live corpus was ACTUALLY loaded from ('disk' or
    'postgres'), or None if not loaded yet. Lets the benchmark manifest record
    what really served the findings, not just the configured intent."""
    return _corpus_source


def _strict_postgres() -> bool:
    try:
        from app.config import settings
        return (getattr(settings, "code_store", "disk").lower() == "postgres"
                and bool(getattr(settings, "code_store_strict", False)))
    except Exception:
        return False


def _load_corpus() -> CodeCorpus:
    """Choose the corpus source. CODE_STORE=postgres uses the DB when populated,
    else falls back to disk JSONL — UNLESS code_store_strict is set, in which
    case a missing/empty DB corpus is fatal (loud, not silently degraded)."""
    global _corpus_source
    try:
        from app.config import settings
        prefer_pg = getattr(settings, "code_store", "disk").lower() == "postgres"
    except Exception:
        prefer_pg = False

    if prefer_pg:
        try:
            from app.code_library import store
            if store.corpus_in_postgres():
                _corpus_source = "postgres"
                return _load_corpus_from_postgres()
            msg = "CODE_STORE=postgres but code_chunks is empty/missing"
            if _strict_postgres():
                raise RuntimeError(f"[code_library] STRICT MODE: {msg} — refusing to "
                                   f"fall back to disk. Apply migration 008 + backfill.")
            logger.warning(f"[code_library] {msg} — falling back to disk JSONL")
        except RuntimeError:
            raise
        except Exception as e:
            if _strict_postgres():
                raise RuntimeError(f"[code_library] STRICT MODE: postgres corpus "
                                   f"load failed: {e}") from e
            logger.warning(f"[code_library] postgres corpus load failed, using disk: {e}")
    _corpus_source = "disk"
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
