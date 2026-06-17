#!/usr/bin/env python
"""Citation walker — verify every statically-emittable citation resolves to a
real ingested section in the CURRENT corpus, the way the RUNTIME does.

WHAT IT WALKS (the two static citation-emission surfaces):
  1. Deterministic rules — BASELINE_RULES + CALFIRE_WUI_RULES +
     CALGREEN_MANDATORY_RULES (rules.py) + LADBS_SFD_RULES (ladbs_rules.py):
     exactly the lists engine.py assembles. engine._to_finding sets the
     finding's source_citation to the WHOLE rule.code_ref, so the gate sees the
     whole string (e.g. "CBC Chapter 7A · CA Gov Code §51182"), not a single
     section — the walker resolves at that whole-code_ref granularity and lists
     each '·'-ref's individual status as supplementary detail.
  2. Checklists — checklists/data/*.json items[].code_citation (one citation per
     finding), each carrying source.edition + jurisdiction.

THE ORACLE — mirrors the runtime, not a reimplementation. The hardened citation
gate (_CorpusProbe._lookup_uncached) resolves a citation by trying each
'·'-separated ref through the corpus's own prefix-guarded lookup
(verify_citation / has_section) — the first that resolves grounds the finding.
There is NO bare-token fallback: that prefix-less loop used to land a naked
number on any code carrying it (504.2 → ADA 504.2, CMC 303.4 → ADA 303.4), and
removing it is what this audit drove. gate_resolve() below mirrors that exactly.
A non-empty CROSS_CODE / VARIANT_DRIFT count here means the leak is back.

ENFORCEMENT PATH decides impact (workflow.py):
  - Deterministic rules → apply_citation_gate(enforce=True). engine sets
    verified = not requires_citation, and the gate SKIPS verified findings. So
    only requires_citation=True rules are gated: if gate_resolve fails their
    NON_COMPLIANT findings are DOWNGRADED to needs_review (true positives
    MUTED). requires_citation=False findings are pre-verified and never gated —
    a bad cite on one is latent hygiene, not a live mis-grounding.
  - Checklists / LLM departments → apply_citation_gate(enforce=False,
    contradiction_guard=True). NEVER muted; a missing section is left alone, a
    wrong-edition/foreign section that DOES resolve attaches its text and is
    only caught if its words don't support the claim (contradiction guard).

NOT walked (stated in the report): LLM department free-form citations — not
statically enumerable; validated at runtime by the same gate.

READ-ONLY. Writes a CSV + markdown fix plan under exports/citation_audit/.
"""
from __future__ import annotations

import csv
import json
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]   # .../repo/backend
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.code_library.corpus_loader import get_corpus  # noqa: E402
from app.code_library.deterministic.rules import (      # noqa: E402
    BASELINE_RULES,
    CALFIRE_WUI_RULES,
    CALGREEN_MANDATORY_RULES,
)
from app.code_library.deterministic.ladbs_rules import LADBS_SFD_RULES  # noqa: E402

CHECKLIST_DIR = BACKEND / "app" / "code_library" / "checklists" / "data"
OUT_DIR = BACKEND.parent / "exports" / "citation_audit"

# rule_id -> known-debt note. Mirrors KNOWN_MISSING in
# tests/test_rule_citation_coverage.py (that test covers BASELINE+WUI+CALGREEN
# only — NOT the LADBS rules, so LADBS gate-mutes here surface as NEW).
KNOWN_MISSING = {
    "FIRE-WUI-VENT": "CBC 708A — retire via licensed 2025 CBC PDF ingest",
    "FIRE-WUI-DECK": "CBC 709A — retire via licensed 2025 CBC PDF ingest",
    "FIRE-WUI-7A": "CBC Chapter 7A — retire via licensed 2025 CBC PDF ingest",
}
try:
    from tests.test_rule_citation_coverage import KNOWN_MISSING as _KM  # noqa: E402
    KNOWN_MISSING = dict(_KM)
except Exception:
    pass

_JURISDICTION_PREFIXES = {"vcbc", "ladbs", "la", "malibu"}
_MODEL_CODES = {
    "ibc", "irc", "crc", "cbc", "cebc", "ifc", "cfc", "imc", "cmc",
    "ipc", "cpc", "nec", "cec", "ada", "calgreen", "cgbc", "iecc", "t24",
}
# Discipline families. A CA code adopts its model code (CEC≈NEC, CMC≈IMC,
# CPC≈IPC, CBC≈IBC, CRC≈IRC), so grounding within a family is a defensible
# match; grounding ACROSS families (a CMC mechanical cite landing on ADA
# accessibility text) is the real cross-code hazard.
_FAMILY = {
    "ibc": "building", "cbc": "building", "cebc": "building", "vcbc": "building",
    "irc": "residential", "crc": "residential",
    "nec": "electrical", "cec": "electrical",
    "imc": "mechanical", "cmc": "mechanical",
    "ipc": "plumbing", "cpc": "plumbing",
    "ifc": "fire", "cfc": "fire",
    "ada": "accessibility",
    "calgreen": "green", "cgbc": "green",
    "iecc": "energy", "t24": "energy",
}
_LEADIN = {"table", "section", "sections", "chapter", "appendix", "figure", "part", "pt"}
_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")


def split_refs(code_ref: str) -> list[str]:
    """Individual citations within a code_ref, split on '·' only (mirrors
    tests/test_rule_citation_coverage.py::_refs). '/' is an authority qualifier,
    not a second citation, so it is NOT split."""
    return [r.strip() for r in code_ref.split("·") if r.strip()]


def year_of(text: str) -> str | None:
    m = _YEAR_RE.search(text or "")
    return m.group(0) if m else None


def short_version(version: str) -> str:
    return year_of(version) or (version or "")[:12]


def has_digit(s: str) -> bool:
    return bool(re.search(r"\d", s or ""))


def intended_code(citation: str) -> str:
    """Best-effort code token a citation starts with ('IBC Table 506.2' ->
    'ibc'); '' when it names no code (a bare number like '504.2')."""
    norm = citation.strip().lower().replace("-", " ").replace("_", " ")
    for tok in re.findall(r"[a-z][a-z0-9&]*", norm):
        if tok in _LEADIN:
            continue
        return tok
    return ""


def same_family(ic: str, rcode: str) -> bool:
    """True if the intended code and grounded code are the same code or the same
    discipline family (CA code ≈ its model code)."""
    if not ic:
        return False
    rparts = rcode.split("-")
    if ic == rcode or ic in rparts or ic in rcode or rcode in ic:
        return True
    g1 = _FAMILY.get(ic)
    g2 = _FAMILY.get(rcode) or _FAMILY.get(rparts[0]) or _FAMILY.get(rparts[-1])
    return bool(g1 and g2 and g1 == g2)


class Resolver:
    def __init__(self) -> None:
        self.corpus = get_corpus()
        self.code_years: dict[str, set[str]] = defaultdict(set)
        for c in self.corpus.chunks:
            y = year_of(c.version)
            if y:
                self.code_years[c.code_short.lower()].add(y)

    # --- the RUNTIME oracle: exact mirror of _CorpusProbe._lookup_uncached ---
    def gate_resolve(self, citation: str):
        """Return (chunk, via) the way the hardened citation gate grounds a
        finding: resolve each '·'-separated ref through the corpus's own
        prefix-guarded lookup; the first that resolves wins. No bare-token
        fallback (that was the cross-code leak this audit drove out). via is
        'ref:<REF>' | None."""
        if not citation:
            return None, None
        for ref in (r.strip() for r in citation.split("·")):
            if ref and self.corpus.has_section(ref):
                return self.corpus.get(ref), f"ref:{ref}"
        return None, None

    def strict_get(self, citation: str):
        """Prefix-guarded corpus.get() — the stricter, non-gate lookup, used to
        show which individual refs are 'really' the cited code vs grounded only
        by the gate's promiscuous bare-token match."""
        return self.corpus.get(citation)

    def per_ref_detail(self, refs: list[str]) -> str:
        out = []
        for r in refs:
            ch = self.strict_get(r)
            out.append(f"{r} → {ch.citation}" if ch else f"{r} → (none)")
        return " ; ".join(out)


def classify_grounding(
    resolver: Resolver,
    citation: str,
    refs: list[str],
    *,
    stated_edition_year: str | None,
) -> dict:
    """Resolve `citation` (whole code_ref for rules; the cite for checklists)
    via the gate oracle and classify the grounding fidelity."""
    out = {
        "citation": citation,
        "status": "",
        "via": "",
        "grounded_citation": "",
        "grounded_code": "",
        "grounded_version": "",
        "primary_ref": refs[0] if refs else citation,
        "primary_in_corpus": "",
        "per_ref": resolver.per_ref_detail(refs) if len(refs) > 1 else "",
        "note": "",
    }
    primary = refs[0] if refs else citation
    primary_chunk = resolver.strict_get(primary)
    out["primary_in_corpus"] = primary_chunk.citation if primary_chunk else ""

    chunk, via = resolver.gate_resolve(citation)
    if chunk is None:
        out["status"] = "DANGLING"
        out["note"] = ("no section number to verify (program/standard reference)"
                       if not has_digit(citation)
                       else "the gate cannot ground this on any loaded edition")
        return out

    out["via"] = via
    out["grounded_citation"] = chunk.citation
    out["grounded_code"] = chunk.code_short
    out["grounded_version"] = chunk.version
    rcode = chunk.code_short.lower()
    rparts = rcode.split("-")
    ryear = year_of(chunk.version)

    # The ·-ref that actually resolved (the gate now grounds on a whole ref,
    # not a bare token).
    owning_ref = via.split(":", 1)[1] if via.startswith("ref:") else citation
    ic = intended_code(owning_ref)

    # (1) checklist edition drift — same code family, different year.
    if stated_edition_year and ryear and same_family(ic, rcode) and stated_edition_year != ryear:
        out["status"] = "EDITION_DRIFT"
        ch3 = bool(re.search(r"\br?3\d", owning_ref.lower()))
        out["note"] = (f"cited {stated_edition_year} edition; grounded on {ryear} "
                       f"corpus chunk — renumbered edition"
                       + (" [CH.3 RENUMBER RISK]" if ch3 else ""))
        return out

    # (2) jurisdiction-variant drift — base cite -> locally amended chunk.
    if rcode != ic and rparts and rparts[0] in _JURISDICTION_PREFIXES and ic not in _JURISDICTION_PREFIXES:
        out["status"] = "VARIANT_DRIFT"
        out["note"] = f"base '{ic}' cite grounded on jurisdiction-amended '{chunk.code_short}'"
        return out

    # (3) cross-code: grounded on a foreign code (different discipline family).
    #     After the gate hardening this should be empty — the prefix-guarded
    #     lookup can no longer land a coded cite on an unrelated code. Confident
    #     only when the ref names a recognized model code (avoids false flags on
    #     fuzzy multi-word prefixes like 'CA Gov Code' -> 'ca' -> GOV).
    if ic in _MODEL_CODES and not same_family(ic, rcode):
        out["status"] = "CROSS_CODE"
        out["note"] = (f"grounded on unrelated '{chunk.citation}' — intended '{ic}'")
        return out

    # (4) grounded, but NOT on the primary named citation (a companion/secondary
    #     ref carried it; the primary section is absent from the corpus).
    if not primary_chunk and owning_ref != primary:
        out["status"] = "GROUNDED_SECONDARY"
        out["note"] = (f"primary citation '{primary}' is NOT in the corpus; rule "
                       f"grounds on '{chunk.citation}' instead — verify that is the "
                       f"right basis")
        return out

    out["status"] = "RESOLVED"
    if len(resolver.code_years.get(ic, set())) > 1:
        out["note"] = f"resolved (note: '{ic}' loaded at editions {','.join(sorted(resolver.code_years[ic]))})"
    return out


# ----------------------------------------------------------------------------
def walk_rules(resolver: Resolver) -> list[dict]:
    rows: list[dict] = []
    for set_name, rules in [
        ("BASELINE_RULES", BASELINE_RULES),
        ("CALFIRE_WUI_RULES", CALFIRE_WUI_RULES),
        ("CALGREEN_MANDATORY_RULES", CALGREEN_MANDATORY_RULES),
        ("LADBS_SFD_RULES", LADBS_SFD_RULES),
    ]:
        for rule in rules:
            refs = split_refs(rule.code_ref)
            c = classify_grounding(resolver, rule.code_ref, refs, stated_edition_year=None)
            rows.append({
                "source_type": "rule",
                "source_set": set_name,
                "source_id": rule.id,
                "context": rule.discipline,
                "requires_citation": rule.requires_citation,
                "enforce_path": "enforce" if rule.requires_citation else "skipped(pre-verified)",
                "raw_code_ref": rule.code_ref,
                "known_debt": KNOWN_MISSING.get(rule.id, ""),
                **c,
            })
    return rows


def walk_checklists(resolver: Resolver) -> list[dict]:
    rows: list[dict] = []
    for fp in sorted(CHECKLIST_DIR.glob("*.json")):
        data = json.loads(fp.read_text(encoding="utf-8"))
        src = data.get("source", {})
        edition, jur = src.get("edition", ""), src.get("jurisdiction", "")
        ed_year = year_of(edition)
        for item in data.get("items", []):
            cite = (item.get("code_citation") or "").strip()
            if not cite:
                continue
            c = classify_grounding(resolver, cite, [cite], stated_edition_year=ed_year)
            rows.append({
                "source_type": "checklist",
                "source_set": fp.name,
                "source_id": f"{data.get('id', fp.stem)}:{item.get('item_id', '?')}",
                "context": f"{jur} | {edition}",
                "requires_citation": "",
                "enforce_path": "enrich(never muted)",
                "raw_code_ref": cite,
                "known_debt": "",
                **c,
            })
    return rows


# ----------------------------------------------------------------------------
CSV_FIELDS = [
    "source_type", "source_set", "source_id", "context", "requires_citation",
    "enforce_path", "raw_code_ref", "citation", "status", "via",
    "grounded_citation", "grounded_code", "grounded_version",
    "primary_ref", "primary_in_corpus", "per_ref", "known_debt", "note",
]
PROBLEM = {"DANGLING", "VARIANT_DRIFT", "EDITION_DRIFT", "CROSS_CODE", "GROUNDED_SECONDARY"}


def write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)


def severity_rank(r: dict) -> int:
    rc = r.get("requires_citation") is True
    if r["status"] == "DANGLING" and rc:
        return 0   # MUTED true positives
    if r["status"] == "GROUNDED_SECONDARY" and rc:
        return 1   # enforced rule grounded on a non-primary section
    if r["status"] == "CROSS_CODE":
        return 2
    if r["status"] == "EDITION_DRIFT":
        return 3
    if r["status"] == "VARIANT_DRIFT":
        return 4
    if r["status"] == "DANGLING":
        return 5
    return 9


def write_fix_plan(path: Path, rows: list[dict]) -> None:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    n_chunks = len(get_corpus().chunks)
    by_status: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_status[r["status"]].append(r)
    rule_rows = [r for r in rows if r["source_type"] == "rule"]
    L: list[str] = []
    A = L.append

    A("# Citation Audit — Fix Plan")
    A("")
    A(f"_Generated {now} against the live corpus ({n_chunks} chunks). Read-only; "
      f"no rule or corpus files were edited._")
    A("")
    A("## Method")
    A("")
    A("Each citation is resolved with the **runtime oracle** — an exact mirror of "
      "the hardened citation gate's `_CorpusProbe`: try each `·`-separated ref "
      "through the corpus's own **prefix-guarded** lookup; the first that resolves "
      "grounds the finding. The old prefix-less bare-token fallback (which landed "
      "`504.2`→`ADA 504.2`, `CMC 303.4`→`ADA 303.4`) has been removed, so "
      "`CROSS_CODE`/`VARIANT_DRIFT` should now be **0** — a non-zero count means "
      "the leak regressed. Severity follows the **enforcement path**:")
    A("")
    A("- **Rules** → `apply_citation_gate(enforce=True)`. The engine sets "
      "`verified = not requires_citation` and the gate skips verified findings, "
      "so **only `requires_citation=True` rules are gated**: if the oracle can't "
      "resolve them, their NON_COMPLIANT findings are **downgraded to "
      "needs_review (true positives muted)**. `requires_citation=False` rules are "
      "pre-verified and never gated — a bad cite there is latent hygiene, not a "
      "live mis-grounding.")
    A("- **Checklists / LLM departments** → `enforce=False` enrich. Never muted; a "
      "wrong-edition/foreign section that resolves attaches its text and is caught "
      "only by the contradiction guard (claim vs cited-text overlap).")
    A("")
    A("Walked: deterministic rules (`code_ref`, whole string, gate granularity) + "
      "checklist `code_citation`s. **Out of scope:** LLM department free-form "
      "cites — not statically enumerable; gated at runtime.")
    A("")

    A("## Summary")
    A("")
    A("| Status | Count | Meaning |")
    A("|---|---:|---|")
    mean = {
        "RESOLVED": "grounds on the intended code & edition",
        "GROUNDED_SECONDARY": "grounds, but on a companion/secondary section (primary cite absent)",
        "DANGLING": "oracle cannot ground it on any loaded edition",
        "EDITION_DRIFT": "grounds on a different edition year than the cite states",
        "VARIANT_DRIFT": "base cite grounds on a jurisdiction-amended variant",
        "CROSS_CODE": "grounds on an unrelated code via bare-token fallback",
    }
    for s in ["RESOLVED", "GROUNDED_SECONDARY", "DANGLING", "EDITION_DRIFT",
              "VARIANT_DRIFT", "CROSS_CODE"]:
        A(f"| {s} | {len(by_status.get(s, []))} | {mean.get(s,'')} |")
    A(f"| **TOTAL** | **{len(rows)}** | citations walked |")
    A("")

    # ---- P0 ----
    muted = sorted([r for r in rule_rows if r["status"] == "DANGLING"
                    and r["requires_citation"] is True],
                   key=lambda r: (r["known_debt"] == "", r["source_id"]))
    A("## P0 — Gate-MUTED rules (`requires_citation=True`, oracle can't resolve)")
    A("")
    A("These produce NON_COMPLIANT findings that the enforce-mode gate silently "
      "**downgrades to needs_review** — confirmed violations that never reach the "
      "customer. Highest priority.")
    A("")
    if muted:
        A("| Rule | code_ref | Known debt? | Fix |")
        A("|---|---|---|---|")
        for r in muted:
            known = r["known_debt"] or "**NEW — not covered by the coverage test**"
            A(f"| `{r['source_id']}` | `{r['raw_code_ref']}` | {known} | "
              f"ingest the section (licensed PDF) or add a KNOWN_MISSING entry |")
        A("")
        A("> The two `LADBS-SFD-*` entries are **new**: "
          "`tests/test_rule_citation_coverage.py` only scans BASELINE + WUI + "
          "CALGREEN, never the LADBS rule list, so these gate-mutes are invisible "
          "to CI today.")
    else:
        A("_None._")
    A("")

    # ---- P1 ----
    sec = sorted([r for r in rule_rows if r["status"] == "GROUNDED_SECONDARY"
                  and r["requires_citation"] is True], key=lambda r: r["source_id"])
    A("## P1 — Enforced rule grounded on a NON-primary citation")
    A("")
    A("`requires_citation=True` and the gate DID ground it — but on a "
      "companion/secondary ref, because the **primary named section is absent**. "
      "Not muted, but the attached provenance is not the section the rule leads "
      "with; confirm it's the right legal basis.")
    A("")
    if sec:
        A("| Rule | code_ref | Primary (absent) | Actually grounds on | via |")
        A("|---|---|---|---|---|")
        for r in sec:
            A(f"| `{r['source_id']}` | `{r['raw_code_ref']}` | `{r['primary_ref']}` | "
              f"`{r['grounded_citation']}` ({r['grounded_code']} "
              f"{short_version(r['grounded_version'])}) | {r['via']} |")
        A("")
        A("> e.g. **FIRE-WUI-7A** names *CBC Chapter 7A* first (absent from corpus) "
          "but grounds on **GOV §51182**, the FHSZ statute it also cites. That is "
          "why it is NOT muted — the companion masks the missing CBC chapter. If "
          "7A text is the intended basis, ingest it.")
    else:
        A("_None._")
    A("")

    # ---- P2 cross-code (any path) ----
    cross = sorted(by_status.get("CROSS_CODE", []), key=severity_rank)
    A("## P2 — Cross-code grounding (bare token lands on the wrong code)")
    A("")
    A("With the gate hardened to resolve each `·`-ref through the corpus's "
      "prefix-guarded lookup (the prefix-less bare-token fallback removed), a "
      "coded citation can no longer ground on an unrelated code. **This class is "
      "now closed** — a non-empty table here would mean the leak regressed.")
    A("")
    if cross:
        A("| Source | req_cit | Citation | Grounds on | via | Note |")
        A("|---|:--:|---|---|---|---|")
        for r in cross:
            A(f"| `{r['source_id']}` | {r['requires_citation']} | `{r['citation']}` | "
              f"`{r['grounded_citation']}` ({r['grounded_code']} "
              f"{short_version(r['grounded_version'])}) | {r['via']} | {r['note']} |")
    else:
        A("_None._")
    A("")
    # latent hygiene: requires_citation=False danglers whose strict lookup would
    # have collided (documented via per_ref), surfaced as a watch-list.
    latent = sorted([r for r in rule_rows if r["status"] == "DANGLING"
                     and r["requires_citation"] is not True and has_digit(r["citation"])],
                    key=lambda r: r["source_id"])
    A("### Latent rule cite-hygiene (inert today — `requires_citation=False`, never gated)")
    A("")
    A("Not muting anything (pre-verified findings), but the cites don't resolve, "
      "so no verbatim provenance attaches. `per_ref` shows which individual "
      "sections are missing vs malformed.")
    A("")
    if latent:
        A("| Rule | code_ref | per-ref strict status |")
        A("|---|---|---|")
        for r in latent:
            A(f"| `{r['source_id']}` | `{r['raw_code_ref']}` | {r['per_ref'] or r['citation'] + ' → (none)'} |")
    else:
        A("_None._")
    A("")

    # ---- P3 checklist clusters ----
    A("## P3 — Checklists cite an edition/code the corpus doesn't carry")
    A("")
    A("Enrich path → **never muted**, but cites either get no grounding or attach "
      "wrong-edition/foreign text (contradiction guard is the only backstop). One "
      "decision per checklist. Chapter-3 (`R3xx`) CRC sections carry the "
      "2022→2025 renumbering (R305→R313, R310→R319, R314/R315→R310/R311) and are "
      "the real verification risk.")
    A("")
    chk = [r for r in rows if r["source_type"] == "checklist"]
    by_file: dict[str, list[dict]] = defaultdict(list)
    for r in chk:
        by_file[r["source_set"]].append(r)
    for fname, items in sorted(by_file.items()):
        cnt = defaultdict(int)
        for r in items:
            cnt[r["status"]] += 1
        ch3 = [r for r in items if "CH.3 RENUMBER RISK" in r["note"]]
        A(f"### `{fname}` — {items[0]['context']}")
        A("")
        A(f"- **{len(items)}** cites: {cnt.get('RESOLVED',0)} clean · "
          f"{cnt.get('EDITION_DRIFT',0)} edition-drift · {cnt.get('CROSS_CODE',0)} "
          f"cross-code grounding · {cnt.get('VARIANT_DRIFT',0)} jurisdiction-variant · "
          f"{cnt.get('GROUNDED_SECONDARY',0)} secondary-ref · {cnt.get('DANGLING',0)} dangling")
        A(f"- **{len(ch3)}** Chapter-3 renumber-risk cites.")
        if cnt.get("RESOLVED", 0) == 0:
            A("- **Verdict:** the corpus carries no clean match for this checklist's "
              "edition — every cite is drifted, cross-grounded, or dangling. Ingest "
              "the stated edition, or do not surface these as verified.")
        else:
            A("- **Verdict:** re-tag to the corpus edition and re-verify each section "
              "survived renumbering (Chapter-3 first), or ingest the stated edition.")
        A("")
        if ch3:
            A("Chapter-3 renumber-risk cites (verify first): "
              + ", ".join(f"`{r['citation']}`" for r in sorted(ch3, key=lambda r: r['source_id'])))
            A("")

    # ---- Appendix ----
    A("## Appendix — informational")
    A("")
    prog = sorted([r for r in rule_rows if r["status"] == "DANGLING" and not has_digit(r["citation"])],
                  key=lambda r: r["source_id"])
    A(f"### By-design non-section references ({len(prog)})")
    A("")
    A("No section number to verify (`LA Emergency Order`, `LADBS plan-content`). "
      "All `requires_citation=False`, so never gated.")
    A("")
    for r in prog:
        A(f"- `{r['raw_code_ref']}` (`{r['source_id']}`)")
    A("")
    path.write_text("\n".join(L), encoding="utf-8")


def main() -> None:
    resolver = Resolver()
    rows = walk_rules(resolver) + walk_checklists(resolver)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    full_csv = OUT_DIR / "citation_audit_full.csv"
    unresolved_csv = OUT_DIR / "citation_audit_unresolved.csv"
    fix_plan = OUT_DIR / "citation_audit_fix_plan.md"

    write_csv(full_csv, rows)
    write_csv(unresolved_csv, sorted([r for r in rows if r["status"] in PROBLEM], key=severity_rank))
    write_fix_plan(fix_plan, rows)

    by_status: dict[str, int] = defaultdict(int)
    for r in rows:
        by_status[r["status"]] += 1
    n_rules = len(BASELINE_RULES) + len(CALFIRE_WUI_RULES) + len(CALGREEN_MANDATORY_RULES) + len(LADBS_SFD_RULES)
    muted = sum(1 for r in rows if r["source_type"] == "rule"
                and r["status"] == "DANGLING" and r["requires_citation"] is True)
    print(f"Walked {len(rows)} citations from {n_rules} rules + "
          f"{len(list(CHECKLIST_DIR.glob('*.json')))} checklists.")
    for k in sorted(by_status):
        print(f"  {k:20s} {by_status[k]}")
    print(f"GATE-MUTED rules (requires_citation, unresolved): {muted}")
    print("Wrote:")
    for p in (full_csv, unresolved_csv, fix_plan):
        print(f"  {p}")


if __name__ == "__main__":
    main()
