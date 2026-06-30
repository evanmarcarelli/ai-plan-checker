"""Every requires_citation=True deterministic rule must be corpus-backed.

When a rule's cited section is missing from the corpus, the enforce-mode
citation gate downgrades the rule's NON_COMPLIANT findings to needs_review —
silently muting TRUE positives. This happened to the CBC Chapter 7A WUI
rules: confirmed fire-zone violations shipped as needs_review because
708A/709A were never ingested.

KNOWN_MISSING is an explicit debt list, not a pass: each entry names the
ingest that retires it. When the section gets ingested, this test FAILS on
the stale entry so the list can't rot.
"""
from app.code_library.adapter import CorpusCodeSource
from app.code_library.deterministic.rules import (
    BASELINE_RULES, CALFIRE_WUI_RULES, CALGREEN_MANDATORY_RULES, CBC_2025_RULES,
)

# rule_id -> why it's missing + what retires the debt.
# FIRE-WUI-DECK is now corpus-backed and removed from this list: in the 2025 code
# cycle the WUI provisions were relocated out of CBC Chapter 7A into the standalone
# California Wildland-Urban Interface Code (Title 24 Part 7) and renumbered, so old
# CBC 709A "Decking" is now WUI Code Section 504.7.3 — ingested as
# corpus/ca_cbc_7a_2025.jsonl (source gov.ca.bsc.wildland.2025). The rule's primary
# code_ref is now "CBC-7A 504.7.3", which the gate counts as a TRUE positive.
# Keep this list empty unless a requires_citation rule's section is genuinely not
# yet in the corpus; each entry must name the ingest that retires it.
KNOWN_MISSING = {}

ALL_RULES = BASELINE_RULES + CALFIRE_WUI_RULES + CALGREEN_MANDATORY_RULES + CBC_2025_RULES


def _refs(rule) -> list:
    return [r.strip() for r in rule.code_ref.split("·") if r.strip()]


def test_citation_rules_are_corpus_backed():
    src = CorpusCodeSource()
    unbacked = []
    stale_known_missing = []
    for rule in ALL_RULES:
        if not rule.requires_citation:
            continue
        found = any(src.verify_citation(ref) for ref in _refs(rule))
        if found and rule.id in KNOWN_MISSING:
            stale_known_missing.append(rule.id)
        elif not found and rule.id not in KNOWN_MISSING:
            unbacked.append(f"{rule.id}: {rule.code_ref}")

    assert not unbacked, (
        "requires_citation rules whose cited sections are NOT in the corpus — "
        "their true positives will be muted by the citation gate. Ingest the "
        "sections or add an explicit KNOWN_MISSING entry:\n  "
        + "\n  ".join(unbacked)
    )
    assert not stale_known_missing, (
        f"KNOWN_MISSING entries now resolved in the corpus — remove them: "
        f"{stale_known_missing}"
    )
