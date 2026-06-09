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

    # ---- jurisdiction scope (single source of truth: the adoption resolver) ----

    def _layers(
        self,
        state: Optional[str],
        city: Optional[str],
        county: Optional[str] = None,
    ) -> Optional[List[str]]:
        """Resolve the corpus layer keys that apply to this jurisdiction via the
        adoption resolver (e.g. CA/Los Angeles -> ['*','CA','CA:Los Angeles']).

        This replaces ad-hoc chunk-level applies_to() matching with the
        authoritative resolver output — the same source that drives code
        versions and amendment labels — so every reviewer scopes to exactly the
        layers in force for the AHJ. Returns None on any failure so callers fall
        back to the legacy geo match (no regression if the map can't load)."""
        if not state:
            return None
        try:
            from app.code_library.adoption.resolver import get_resolver
            keys = get_resolver().resolve(state, county, city).corpus_layer_keys
            return list(keys) if keys else None
        except Exception:
            return None

    # ---- read paths ----

    def get_applicable_codes(
        self,
        state: Optional[str],
        city: Optional[str],
        plan_type: str = "commercial",
        county: Optional[str] = None,
    ) -> List[CodeRequirement]:
        layers = self._layers(state, city, county)
        if layers is not None:
            return [chunk_to_requirement(c) for c in self._corpus.chunks if c.in_layers(layers)]
        return [chunk_to_requirement(c) for c in self._corpus.chunks if c.applies_to(state, city)]

    def get_codes_by_category(
        self,
        category: str,
        state: Optional[str],
        city: Optional[str],
        plan_type: str = "commercial",
        county: Optional[str] = None,
    ) -> List[CodeRequirement]:
        layers = self._layers(state, city, county)
        return [chunk_to_requirement(c) for c
                in self._retriever.all_for_category(category, state=state, city=city, layer_keys=layers)]

    # ---- retrieval (new) ----

    def retrieve(
        self,
        query: str,
        *,
        category: Optional[str] = None,
        state: Optional[str] = None,
        city: Optional[str] = None,
        county: Optional[str] = None,
        k: int = 6,
    ) -> List[CodeRequirement]:
        """BM25 search for the most relevant code chunks given a free-text query.

        Department agents call this to augment their baseline 'must-check' list
        with whatever specifically applies to the page content they're reading.
        """
        layers = self._layers(state, city, county)
        chunks = self._retriever.search(
            query, category=category, state=state, city=city, layer_keys=layers, k=k,
        )
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

    # ---- jurisdiction metadata (delegated to the adoption map) ----

    def get_jurisdiction_amendments(
        self, state: Optional[str], city: Optional[str], county: Optional[str] = None
    ) -> List[str]:
        """Local amendment labels for a jurisdiction, from the adoption map.

        Replaces the old corpus-scan + hardcoded heuristics. Returns the
        discipline-tagged local amendments (e.g. "building: LABC — LAMC Ch.
        IX, Art. 1") plus an authority line.
        """
        from app.code_library.adoption.resolver import get_resolver

        if not state:
            return []
        stack = get_resolver().resolve(state, county, city)
        out: List[str] = []
        if stack.authority and stack.level != "state":
            out.append(f"AHJ: {stack.authority}")
        for disc, label in stack.amendments.items():
            out.append(f"{disc}: {label}")
        return out

    def get_code_version(
        self, state: Optional[str], city: Optional[str] = None, county: Optional[str] = None
    ) -> str:
        """Headline adopted code version from the adoption map.

        Was a hardcoded dict that had gone stale ("2022 CA Building Code");
        now resolves the live edition (e.g. 2025 CBC for LA) via the map.
        """
        from app.code_library.adoption.resolver import get_resolver

        if not state:
            return "2021 IBC"
        return get_resolver().resolve(state, county, city).headline_code_version()
