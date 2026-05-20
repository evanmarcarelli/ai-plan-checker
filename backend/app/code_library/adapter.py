"""Adapter that exposes the CodeDatabase interface backed by the real corpus.

This is the drop-in replacement for services.code_database.CodeDatabase.
The legacy hardcoded BUILDING_CODES_DB is preserved in services/code_database.py
as a fallback (and for the jurisdiction-amendment notes), but every actual
code requirement now comes from the JSONL corpus + BM25 retriever.
"""
from typing import List, Optional

from app.code_library.corpus_loader import CodeChunk, get_corpus, get_retriever
from app.models.schemas import CodeRequirement


def chunk_to_requirement(chunk: CodeChunk) -> CodeRequirement:
    """Convert a CodeChunk → CodeRequirement so existing agent code keeps working."""
    return CodeRequirement(
        code_id=chunk.citation,           # canonical, verifiable citation
        code_name=chunk.code_name,
        section=chunk.section,
        description=chunk.title or chunk.text[:120],
        category=chunk.category,
        requirement_type="general",
        jurisdiction_specific=("*" not in chunk.jurisdictions),
        full_text=chunk.text,             # VERBATIM code text — the grounding
        source=f"code_library:{chunk.code_short.lower()}-{chunk.version}",
    )


class CorpusCodeSource:
    """Drop-in replacement for CodeDatabase.

    Implements get_applicable_codes / get_codes_by_category / get_jurisdiction_amendments
    / get_code_version using the BM25-indexed corpus.
    """

    def __init__(self) -> None:
        self._corpus = get_corpus()
        self._retriever = get_retriever()

    # ---- read paths ----

    def get_applicable_codes(
        self,
        state: Optional[str],
        city: Optional[str],
        plan_type: str = "commercial",
    ) -> List[CodeRequirement]:
        return [chunk_to_requirement(c) for c in self._corpus.chunks
                if c.applies_to(state, city)]

    def get_codes_by_category(
        self,
        category: str,
        state: Optional[str],
        city: Optional[str],
        plan_type: str = "commercial",
    ) -> List[CodeRequirement]:
        return [chunk_to_requirement(c) for c
                in self._retriever.all_for_category(category, state=state, city=city)]

    # ---- retrieval (new) ----

    def retrieve(
        self,
        query: str,
        *,
        category: Optional[str] = None,
        state: Optional[str] = None,
        city: Optional[str] = None,
        k: int = 6,
    ) -> List[CodeRequirement]:
        """BM25 search for the most relevant code chunks given a free-text query.

        Department agents call this to augment their baseline 'must-check' list
        with whatever specifically applies to the page content they're reading.
        """
        chunks = self._retriever.search(query, category=category, state=state, city=city, k=k)
        return [chunk_to_requirement(c) for c in chunks]

    # ---- verification ----

    def verify_citation(self, citation_or_section: str) -> bool:
        """Return True iff the citation string corresponds to a real chunk
        in the corpus. Used to filter out hallucinated section numbers."""
        return self._corpus.has_section(citation_or_section)

    def get_source_text(self, citation_or_section: str) -> Optional[str]:
        """Return the verbatim code text for a citation, or None if not in corpus."""
        chunk = self._corpus.get(citation_or_section)
        return chunk.text if chunk else None

    # ---- jurisdiction metadata (delegated to legacy DB for amendment notes) ----

    def get_jurisdiction_amendments(self, state: Optional[str], city: Optional[str]) -> List[str]:
        # Build from corpus: any chunk whose jurisdictions include this state
        if not state:
            return []
        state_u = state.upper()
        amendments: List[str] = []
        seen = set()
        for c in self._corpus.chunks:
            for j in c.jurisdictions:
                key = j.upper()
                if "*" in key:
                    continue
                if key == state_u or key.startswith(state_u + ":"):
                    label = f"{c.code_name} ({c.version})"
                    if label not in seen:
                        amendments.append(label)
                        seen.add(label)
        # Stable extras for known triggers
        if state_u == "CA":
            if city:
                if "altadena" in city.lower() or "pasadena" in city.lower():
                    amendments.append("LA County Building & Safety jurisdiction")
                    amendments.append("CBC Chapter 7A (WUI) — Eaton Fire rebuild zone")
                if "los angeles" in city.lower():
                    amendments.append("LADBS requirements apply")
        return amendments

    def get_code_version(self, state: Optional[str]) -> str:
        # Pick the most modern primary building code available in the corpus
        versions = {
            "CA": "2022 California Building Code + Title 24 Part 6",
            "FL": "2023 Florida Building Code",
            "NY": "2022 NYC Building Code",
            "TX": "2021 IBC with Texas amendments",
            "WA": "2021 Washington State Building Code",
        }
        if not state:
            return "2021 IBC"
        return versions.get(state.upper(), "2021 IBC")
