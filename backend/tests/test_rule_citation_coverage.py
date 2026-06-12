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
    BASELINE_RULES, CALFIRE_WUI_RULES, CALGREEN_MANDATORY_RULES,
)

# rule_id -> why it's missing + what retires the debt.
KNOWN_MISSING = {
    "FIRE-WUI-VENT": "CBC 708A — retire via licensed 2025 CBC PDF ingest",
    "FIRE-WUI-DECK": "CBC 709A — retire via licensed 2025 CBC PDF ingest",
    "FIRE-WUI-7A": "CBC Chapter 7A — retire via licensed 2025 CBC PDF ingest",
}

ALL_RULES = BASELINE_RULES + CALFIRE_WUI_RULES + CALGREEN_MANDATORY_RULES


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
