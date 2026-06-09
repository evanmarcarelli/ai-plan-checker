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
            if not chunk.applies_to(state, city):
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
        limit: Optional[int] = None,
    ) -> List[CodeChunk]:
        """Return every chunk in a category, jurisdiction-filtered. Used by department
        agents as the baseline 'must check' list (RAG augments, doesn't replace)."""
        result = [c for c in self.corpus.chunks
                  if c.category == category and c.applies_to(state, city)]
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


_corpus_lock = threading.RLock()
_corpus_singleton: Optional[CodeCorpus] = None
_retriever_singleton: Optional[CodeRetriever] = None


def get_corpus() -> CodeCorpus:
    global _corpus_singleton
    with _corpus_lock:
        if _corpus_singleton is None:
            _corpus_singleton = _load_corpus_from_disk()
        return _corpus_singleton


def get_retriever() -> CodeRetriever:
    global _retriever_singleton
    with _corpus_lock:
        if _retriever_singleton is None:
            _retriever_singleton = CodeRetriever(get_corpus())
        return _retriever_singleton


def reload_corpus() -> CodeCorpus:
    """Force a reload from disk — useful in tests and after ingesting new files."""
    global _corpus_singleton, _retriever_singleton
    with _corpus_lock:
        _corpus_singleton = _load_corpus_from_disk()
        _retriever_singleton = CodeRetriever(_corpus_singleton)
        return _corpus_singleton
