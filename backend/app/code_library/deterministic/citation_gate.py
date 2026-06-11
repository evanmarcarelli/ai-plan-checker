"""Citation gate.

Ported in spirit from plan-room-ahj's corpus citation pre-check (Part 5).
The rule: a finding that asserts a *code interpretation* (an allowable-area
violation, a story-limit violation) must be backed by verbatim code text from
the corpus before it is surfaced to the customer as a hard NON_COMPLIANT. If
the cited section can't be found in the corpus, we don't delete the finding —
we downgrade it to NEEDS_REVIEW and flag it, so a human confirms it against
the actual code rather than trusting an unverifiable citation.

Two modes:
  - enforce=True  (deterministic numeric/table findings): downgrade
    NON_COMPLIANT -> NEEDS_REVIEW when the citation isn't in the corpus.
    These are the assertions that lose the customer if the citation is wrong.
  - enforce=False (LLM department findings): ENRICH only. Attach verbatim
    source_text + verified=True when the citation is in the corpus, but never
    downgrade for a MISSING section — the corpus is too thin to be
    authoritative against, and the department reviews stand on their own
    retrieval.

The CONTRADICTION GUARD (contradiction_guard=True) closes the subtler LLM
failure mode the missing-section rule can't: the model cites a section that
IS in the corpus, but the section's text doesn't support the claim at all
(wrong-section cite, or an invented requirement hung on a real number).
For text we HAVE, the corpus is authoritative — so a NON_COMPLIANT whose
claim shares no significant phrase or bigram with the cited section's text
is downgraded to NEEDS_REVIEW with the dissent note attached. Findings whose
sections are missing from the corpus are still left alone in enrich mode.

Either way, every finding that CAN be grounded gets verified=True and the
verbatim source_text attached, which is the provenance an E&O carrier or
appeal hearing asks for.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Optional

from app.models.schemas import ComplianceFinding, ComplianceStatus

# A section token inside a citation string, e.g. "506.2", "7A", "1006.3.2",
# "230.42", "R401". Used to probe the corpus when the full citation string
# ("IBC Table 506.2") doesn't match a chunk id directly.
_SECTION_TOKEN_RE = re.compile(r"\b([A-Z]?\d+[A-Z]?(?:\.\d+[A-Z]?)*)\b")

_UNVERIFIED_NOTE = (
    " [Citation unverified against code corpus — confirm against the adopted "
    "code before issuing. Downgraded from non-compliant to needs-review.]"
)

_CONTRADICTED_NOTE = (
    " [The cited section exists in the code corpus but its text does not "
    "support this claim — likely a wrong-section citation. Confirm against "
    "the adopted code before issuing. Downgraded from non-compliant to "
    "needs-review.]"
)


@dataclass
class GateStats:
    checked: int = 0
    verified: int = 0
    downgraded: int = 0
    contradicted: int = 0


class _CorpusProbe:
    """Adapts whatever code source is available to verify/get_source_text.

    The real source is CorpusCodeSource (has verify_citation + get_source_text).
    A tiny duck-typed protocol keeps this testable with a fake. Lookups are
    memoized per probe instance — findings in one run repeat the same handful
    of citations (Table 506.2, 1006.3.2 ...) many times over.
    """

    def __init__(self, code_source):
        self._src = code_source
        self._memo: Dict[str, Optional[str]] = {}

    def lookup(self, citation: str) -> Optional[str]:
        """Return verbatim source text if the citation (or any section token
        inside it) is in the corpus, else None."""
        if not citation:
            return None
        if citation in self._memo:
            return self._memo[citation]
        result = self._lookup_uncached(citation)
        self._memo[citation] = result
        return result

    def _lookup_uncached(self, citation: str) -> Optional[str]:
        # 1. Try the whole citation string.
        if self._src.verify_citation(citation):
            return self._src.get_source_text(citation) or ""
        # 2. Try each section-number token found in the string.
        for tok in _SECTION_TOKEN_RE.findall(citation.upper()):
            if self._src.verify_citation(tok):
                return self._src.get_source_text(tok) or ""
        return None


def _claim_supported_by(source_text: str, claim: str) -> bool:
    """True when the claim is at least topically supported by the source
    text — a shared significant phrase (VERIFIED) or ≥2 shared bigrams
    (PARTIAL), mirroring citation_retrieval's quality grading. False means
    SECTION_ONLY: the section says something else entirely."""
    from app.code_library.citation_retrieval import (
        _bigram_overlap,
        _significant_tokens,
        find_supporting_text,
    )

    if not source_text or not claim:
        return True  # nothing to judge against — don't punish the finding
    if find_supporting_text(source_text, claim) is not None:
        return True
    return _bigram_overlap(
        _significant_tokens(claim), _significant_tokens(source_text)
    ) >= 2


def apply_citation_gate(
    findings: List[ComplianceFinding],
    code_source,
    *,
    enforce: bool = True,
    contradiction_guard: bool = False,
) -> GateStats:
    """Verify/ground each finding's citation in place. Returns stats.

    Mutates the findings list: sets verified / source_text, and (when
    enforce=True) downgrades unverifiable NON_COMPLIANT findings to
    NEEDS_REVIEW with a flag appended to the description. When
    contradiction_guard=True, a NON_COMPLIANT finding whose cited section IS
    in the corpus but whose text does not support the claim is also
    downgraded (see module docstring).
    """
    probe = _CorpusProbe(code_source)
    stats = GateStats()

    for f in findings:
        # Declarative findings already grounded (verified=True, no citation
        # needed) are left alone — a missing sprinkler note needs no quote.
        if f.verified:
            continue

        stats.checked += 1
        citation = f.source_citation or f.code_requirement.section or f.code_requirement.code_id
        source_text = probe.lookup(citation or "")

        if source_text is not None:
            f.verified = True
            f.source_text = source_text or None
            stats.verified += 1
            # Contradiction guard: we HAVE the section's text — for text we
            # have, the corpus is authoritative. A hard violation whose claim
            # the text doesn't even topically support is a likely wrong cite.
            if (
                contradiction_guard
                and source_text
                and f.status == ComplianceStatus.NON_COMPLIANT
                and not _claim_supported_by(source_text, f.description or "")
            ):
                f.status = ComplianceStatus.NEEDS_REVIEW
                if _CONTRADICTED_NOTE.strip() not in (f.description or ""):
                    f.description = (f.description or "") + _CONTRADICTED_NOTE
                stats.contradicted += 1
                stats.downgraded += 1
            continue

        # Unverifiable citation.
        if enforce and f.status == ComplianceStatus.NON_COMPLIANT:
            f.status = ComplianceStatus.NEEDS_REVIEW
            if _UNVERIFIED_NOTE.strip() not in (f.description or ""):
                f.description = (f.description or "") + _UNVERIFIED_NOTE
            stats.downgraded += 1

    return stats
