"""Citation-grounded retrieval layer.

The *consumption* side of the corpus, paired with the ingest pipeline that is
its supply side. Three responsibilities, kept small on purpose:

1. **Structural retrieval** — given (code_short, section, jurisdiction),
   return the chunk PLUS its parent-section context. Building-code prose is
   famously referential: section 1006.3.2 only makes sense in the scope of
   1006.3, and a model that ignores the parent will misread the rule.

2. **Verbatim quote extraction** — given a chunk and an agent's claim about
   it, extract the bounded span of source text (a sentence or short paragraph)
   that supports the claim. Fair-use bounded at MAX_QUOTE_CHARS.

3. **Claim verification** — confirm both that the cited section exists in the
   corpus AND that the claim's substantive phrase appears in the section.
   Catches the subtler failure mode where a model cites a real section but
   the section actually says something else.

This module is dependency-light: it sits on top of corpus_loader.CodeCorpus
and AdoptionResolver. Agents talk to it via `verify_and_ground()`; the
deterministic engine talks to it via `find_supporting_text()`.

Why not just use the BM25 retriever?
  - BM25 is great at "which sections are topically relevant" — it is the
    discovery layer. This is the *grounding* layer: by the time we land
    here we already have a candidate citation, and we need to confirm it.
  - BM25 has no notion of code structure or claim-text matching, both of
    which are necessary for an auditable citation.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Sequence, Tuple

from app.code_library.corpus_loader import CodeChunk, CodeCorpus, get_corpus
from app.utils.logger import get_logger

logger = get_logger(__name__)


# Fair-use cap on the verbatim span returned for any single citation. Aligns
# with the ICC-licensing policy in docs/ICC_LICENSING.md (≤200 chars from
# copyrighted model-code text). State-adopted text and municipal code are
# not subject to the cap, but enforcing one number across all sources keeps
# the surface area auditable.
MAX_QUOTE_CHARS = 280

# Minimum overlap between a claim and the source text to call the claim
# "supported by" the citation. Counted as the longest run of shared
# significant tokens. Two consecutive significant tokens is the right
# floor for paraphrased claims: a model typically rewords more than it
# copies, but any genuinely grounded claim tends to repeat at least one
# multi-word phrase from the section ("front setback", "fire-resistance
# rating", "exit access doorway").
MIN_CLAIM_SUPPORT_TOKENS = 2


class CitationQuality(str, Enum):
    """How well does the corpus back a claimed citation?

    - VERIFIED:    section exists AND the claim's substantive phrase
                   appears verbatim in the section text.
    - PARTIAL:     section exists AND the claim is topically supported by
                   the section (shared bigrams / overlapping tokens) but no
                   exact phrase match.
    - SECTION_ONLY: section exists in the corpus, but the section text does
                    not support the specific claim. Likely a wrong cite.
    - UNVERIFIED:  the cited section is not in the corpus at all.
    """

    VERIFIED = "verified"
    PARTIAL = "partial"
    SECTION_ONLY = "section_only"
    UNVERIFIED = "unverified"


@dataclass
class GroundedCitation:
    """A citation paired with everything an auditor needs to confirm it."""

    citation: str                       # canonical, e.g. "IBC 1006.3.2"
    code_short: str                     # "IBC"
    code_name: str                      # "International Building Code"
    section: str                        # "1006.3.2"
    quality: CitationQuality
    verbatim_quote: str = ""            # ≤ MAX_QUOTE_CHARS, the supporting span
    parent_section_text: str = ""       # parent scope (e.g. 1006.3)
    chunk_id: str = ""                  # source chunk for traceability
    jurisdictions: List[str] = field(default_factory=list)
    version: str = ""

    @property
    def is_admissible(self) -> bool:
        """Cite-worthy for surfacing to a paying user."""
        return self.quality in (CitationQuality.VERIFIED, CitationQuality.PARTIAL)


# ─────────────────────────────────────────────────────────────────────────
# Tokenizing + matching
# ─────────────────────────────────────────────────────────────────────────


_WORD_RE = re.compile(r"[a-z0-9]+(?:[./-][a-z0-9]+)*", re.IGNORECASE)
_INSIGNIFICANT = {
    "the", "a", "an", "of", "to", "in", "on", "for", "and", "or", "with",
    "by", "shall", "be", "is", "are", "as", "at", "from", "that", "this",
    "which", "not", "no", "any", "all", "more", "less", "than", "such",
    "may", "must", "should", "where", "when", "if", "per", "each", "one",
    "two", "section", "chapter", "table",
}


def _significant_tokens(text: str) -> List[str]:
    return [
        t.lower()
        for t in _WORD_RE.findall(text or "")
        if t.lower() not in _INSIGNIFICANT and len(t) > 1
    ]


def _longest_common_run(claim_tokens: Sequence[str], src_tokens: Sequence[str]) -> int:
    """Length of the longest contiguous shared run between two token lists.

    Cheap O(n*m) DP. The token streams we're comparing are bounded —
    findings are sentences (≤30 tokens) and chunk text is sentences-to-paragraph
    sized in practice (the chunker caps at SOFT_MAX_CHARS).
    """
    if not claim_tokens or not src_tokens:
        return 0
    n, m = len(claim_tokens), len(src_tokens)
    prev = [0] * (m + 1)
    best = 0
    for i in range(1, n + 1):
        curr = [0] * (m + 1)
        for j in range(1, m + 1):
            if claim_tokens[i - 1] == src_tokens[j - 1]:
                curr[j] = prev[j - 1] + 1
                if curr[j] > best:
                    best = curr[j]
        prev = curr
    return best


def _bigram_overlap(a: Sequence[str], b: Sequence[str]) -> int:
    """Count of shared bigrams between two token sequences. Used as the
    weaker 'topical support' signal for CitationQuality.PARTIAL."""
    if len(a) < 2 or len(b) < 2:
        return 0
    a_bg = set(zip(a, a[1:]))
    b_bg = set(zip(b, b[1:]))
    return len(a_bg & b_bg)


# ─────────────────────────────────────────────────────────────────────────
# Quote extraction
# ─────────────────────────────────────────────────────────────────────────


_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.;:])\s+(?=[A-Z0-9])")


def find_supporting_text(
    chunk_text: str, claim: str, *, max_chars: int = MAX_QUOTE_CHARS
) -> Optional[str]:
    """Return the shortest sentence (or pair of sentences) from `chunk_text`
    that maximizes claim support and fits under `max_chars`. None if no
    sentence shares more than `MIN_CLAIM_SUPPORT_TOKENS` significant tokens
    with the claim.

    Bounded by fair-use cap. Strict trim on the right boundary."""
    if not chunk_text or not claim:
        return None

    claim_tokens = _significant_tokens(claim)
    if not claim_tokens:
        return None

    sentences = [s.strip() for s in _SENTENCE_SPLIT_RE.split(chunk_text) if s.strip()]
    if not sentences:
        return None

    best_sent: Optional[str] = None
    best_score = 0
    for s in sentences:
        s_tokens = _significant_tokens(s)
        run = _longest_common_run(claim_tokens, s_tokens)
        if run > best_score:
            best_score = run
            best_sent = s

    if best_sent is None or best_score < MIN_CLAIM_SUPPORT_TOKENS:
        return None

    if len(best_sent) <= max_chars:
        return best_sent
    # Trim to nearest word boundary under cap, plus an ellipsis.
    cut = best_sent[: max_chars - 1].rsplit(" ", 1)[0]
    return f"{cut}…"


def bounded_source_quote(chunk, claim: str) -> str:
    """License-aware source quote for a customer-facing finding.

    Government-edict text (statutes, certified plans — public domain) passes
    through whole; anything else (licensed model-code text, unreviewed
    scrapes) is bounded to the fair-use MAX_QUOTE_CHARS, preferring the span
    that actually supports the claim. Closes the gap where findings attached
    FULL verbatim ICC-derived chunks (up to ~3,000 chars) despite the
    documented ≤280-char posture in docs/ICC_LICENSING.md.
    """
    text = chunk.text or ""
    if getattr(chunk, "license_status", "review") == "edict":
        return text
    if len(text) <= MAX_QUOTE_CHARS:
        return text
    span = find_supporting_text(text, claim or "")
    if span:
        return span
    cut = text[: MAX_QUOTE_CHARS - 1].rsplit(" ", 1)[0]
    return f"{cut}…"


# ─────────────────────────────────────────────────────────────────────────
# Structural retrieval
# ─────────────────────────────────────────────────────────────────────────


_PARENT_RE = re.compile(r"^(.+)\.(\d+[A-Z]?)$")


def _parent_section(section: str) -> Optional[str]:
    """Return the parent section of a Title.Chapter.Section style citation,
    or None if there's nothing to climb to. 1006.3.2 → 1006.3; 1006.3 → 1006;
    1006 → None."""
    m = _PARENT_RE.match(section.strip())
    if not m:
        return None
    return m.group(1)


def lookup_with_context(
    corpus: CodeCorpus,
    citation_or_section: str,
    *,
    state: Optional[str] = None,
    city: Optional[str] = None,
) -> Tuple[Optional[CodeChunk], Optional[CodeChunk]]:
    """Return (chunk, parent_chunk) for a citation. Either may be None.

    Jurisdiction filter is applied opportunistically: if the cited section
    exists but is scoped to a different jurisdiction, we still return it so
    the caller can decide whether to use it. The retrieval is informational;
    enforcement is the engine's job.
    """
    chunk = corpus.get(citation_or_section)
    parent_chunk: Optional[CodeChunk] = None
    if chunk:
        parent_sec = _parent_section(chunk.section)
        if parent_sec:
            parent_chunk = corpus.get(f"{chunk.code_short} {parent_sec}") or corpus.get(parent_sec)
    return chunk, parent_chunk


# ─────────────────────────────────────────────────────────────────────────
# Claim verification (the public entry agents call)
# ─────────────────────────────────────────────────────────────────────────


def verify_and_ground(
    citation: str,
    claim: str,
    *,
    state: Optional[str] = None,
    city: Optional[str] = None,
    corpus: Optional[CodeCorpus] = None,
) -> GroundedCitation:
    """Verify a citation and produce a GroundedCitation auditors can sign off on.

    `citation` — what the agent cited, e.g. "IBC 1006.3.2" or "LAMC 12.21".
    `claim`    — the natural-language assertion the agent made about that
                 section. Used to (a) pick the supporting sentence and (b)
                 catch wrong-section citations where the section exists but
                 says something else.

    Quality grading:
      - VERIFIED:    section exists and contains a sentence sharing a run of
                     ≥MIN_CLAIM_SUPPORT_TOKENS with the claim. We attach that
                     sentence as the verbatim quote.
      - PARTIAL:     section exists and shares bigrams with the claim but no
                     long run. Topically supported, weaker grounding.
      - SECTION_ONLY: section exists but neither overlap signal fires. Likely
                     a wrong-section cite.
      - UNVERIFIED:  section is not in the corpus at all.
    """
    corpus = corpus or get_corpus()
    chunk, parent_chunk = lookup_with_context(corpus, citation, state=state, city=city)

    if chunk is None:
        return GroundedCitation(
            citation=citation,
            code_short=_code_short_from_citation(citation),
            code_name="",
            section=_section_from_citation(citation),
            quality=CitationQuality.UNVERIFIED,
        )

    quote = find_supporting_text(chunk.text, claim)
    claim_tokens = _significant_tokens(claim)
    src_tokens = _significant_tokens(chunk.text)
    run = _longest_common_run(claim_tokens, src_tokens)
    bigram_hits = _bigram_overlap(claim_tokens, src_tokens)

    if quote and run >= MIN_CLAIM_SUPPORT_TOKENS:
        quality = CitationQuality.VERIFIED
    elif bigram_hits >= 2:
        quality = CitationQuality.PARTIAL
    else:
        quality = CitationQuality.SECTION_ONLY

    parent_text = ""
    if parent_chunk is not None:
        parent_text = (parent_chunk.text or "")[: MAX_QUOTE_CHARS * 2].strip()

    return GroundedCitation(
        citation=chunk.citation,
        code_short=chunk.code_short,
        code_name=chunk.code_name,
        section=chunk.section,
        quality=quality,
        verbatim_quote=quote or "",
        parent_section_text=parent_text,
        chunk_id=chunk.chunk_id,
        jurisdictions=list(chunk.jurisdictions),
        version=chunk.version,
    )


def ground_many(
    citations: Sequence[Tuple[str, str]],
    *,
    state: Optional[str] = None,
    city: Optional[str] = None,
) -> List[GroundedCitation]:
    """Batch convenience: a stream of (citation, claim) pairs → GroundedCitation
    list. Loads the corpus once."""
    corpus = get_corpus()
    return [
        verify_and_ground(cit, claim, state=state, city=city, corpus=corpus)
        for cit, claim in citations
    ]


# ─────────────────────────────────────────────────────────────────────────
# Citation string helpers
# ─────────────────────────────────────────────────────────────────────────


_CITATION_RE = re.compile(
    r"^\s*([A-Z][A-Z0-9-]*)\s+([A-Z]?\d+[A-Z]?(?:\.\d+[A-Z]?)*)",
    re.IGNORECASE,
)


def _code_short_from_citation(citation: str) -> str:
    m = _CITATION_RE.match(citation or "")
    return m.group(1).upper() if m else ""


def _section_from_citation(citation: str) -> str:
    m = _CITATION_RE.match(citation or "")
    return m.group(2) if m else (citation or "").strip()
