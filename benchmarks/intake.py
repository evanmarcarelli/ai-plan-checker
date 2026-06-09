"""Correction-letter intake — scaffold a ground_truth.yaml from a real letter.

A city correction letter is the gold ground truth (BENCHMARK_DESIGN §2, Tier C),
but transcribing one into the benchmark schema by hand is slow and error-prone.
This parses a letter (PDF or text), pulls out the numbered correction items and
the code sections each cites, guesses severity/status/objectivity, flags the
administrative items, and emits a heavily-annotated `ground_truth.yaml` SCAFFOLD.

It is explicitly NOT ground truth on its own — a licensed reviewer still must
verify every guess, fill the acceptance_criteria, add equivalent citations, and
delete the administrative noise. The point is to turn an hour of transcription
into ten minutes of review.

    python -m benchmarks.intake corrections.pdf --case-id la_sfr_042 \\
        --jurisdiction CA:Los Angeles --plan-type residential

The parsing functions are pure and DB/PDF-free so they're unit-tested directly.
"""
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

# Code prefixes we recognize in a citation. Longest-first so 'CBC-7A' wins over
# 'CBC'. Extend as you encounter new jurisdictions.
_CODE_PREFIXES = [
    "CBC-7A", "CBC7A", "CALGREEN", "CALGreen", "CalGreen", "Title 24", "Title24",
    "CBC", "CRC", "IBC", "IRC", "IFC", "CFC", "CEC", "NEC", "CPC", "IPC", "CMC",
    "IMC", "ADA", "T24", "LAMC", "LABC", "LAPC", "LAEC", "LAGBC", "NFPA", "ASCE",
    "PRC", "CGBSC",
]
_PREFIX_ALT = "|".join(sorted((re.escape(p) for p in _CODE_PREFIXES), key=len, reverse=True))
# PREFIX [Table|Section|§] NUMBER  — number allows 704A.1, R337.7, 210.8(A), etc.
_NUM = r"[A-Za-z]?\d[\dA-Za-z.\-]*(?:\([A-Za-z0-9]+\))?"
_CITE_RE = re.compile(rf"\b({_PREFIX_ALT})\b[\s\-]*"
                      rf"(?:Table\s+|Sec(?:tion|\.)?\s+|§\s*)?({_NUM})", re.IGNORECASE)
# Bare residential R-sections (CRC), captured even without an explicit prefix.
_R_RE = re.compile(r"\bR\d+(?:\.\d+[A-Za-z]?)*\b")

# Item splitter: lines that start a numbered correction ("1.", "2)", "Item 3", "#4").
_ITEM_RE = re.compile(r"(?m)^\s*(?:item\s*)?#?\s*(\d{1,3})[.)\-:]\s+", re.IGNORECASE)

# Keywords are matched WHOLE-WORD (\b..\b) so 'fee' doesn't match 'feet' — use
# explicit inflections (e.g. 'stamped') rather than stems.
_SEV_CRITICAL = ("life safety", "egress", "exit", "exiting", "means of egress",
                 "fire-rated", "fire rating", "fire-resistance", "occupancy separation",
                 "structural", "guard", "guardrail", "smoke alarm", "sprinkler", "shaft",
                 "fire wall", "fire barrier", "rescue", "fire separation")
_SEV_HIGH = ("accessible", "accessibility", "ada", "handrail", "stair", "stairs",
             "ramp", "fire", "energy", "ventilation", "light and ventilation",
             "defensible space", "wui", "weather", "exterior wall", "ember", "title 24")
_ADMIN_HINTS = ("fee", "fees", "signature", "signed", "wet sign", "wet-sign",
                "stamp", "stamped", "incomplete", "application", "missing form",
                "deferred submittal", "resubmit", "smip", "valuation",
                "owner-builder", "notary")
_INFO_REQUEST = ("provide", "clarify", "show", "indicate", "submit", "specify",
                 "identify", "label", "dimension")
_NONCOMPLY = ("does not comply", "not comply", "violation", "shall", "required",
              "exceeds", "less than", "not permitted", "minimum", "maximum")
_MEASURABLE = re.compile(r"\d+\s*(?:\"|''|in\.?|inch|ft\.?|feet|foot|sf|sq|%|percent|"
                         r"min|max|degree)", re.IGNORECASE)


def _has(text: str, keywords) -> bool:
    """Whole-word keyword match (so 'fee' != 'feet', 'ada' != 'Nevada')."""
    t = (text or "").lower()
    return any(re.search(r"\b" + re.escape(kw) + r"\b", t) for kw in keywords)


@dataclass
class CorrectionItem:
    number: Optional[int]
    raw_text: str
    sections: List[str] = field(default_factory=list)
    severity: str = "medium"
    status: str = "non_compliant"
    objectivity: str = "soft"
    is_administrative: bool = False
    issue_id: str = ""


# ── pure parsing ─────────────────────────────────────────────

def find_sections(text: str) -> List[str]:
    """All code citations in a blob, normalized to 'PREFIX NUMBER', de-duped,
    order-preserving. Bare R-sections are kept as-is for the reviewer to prefix."""
    out: List[str] = []
    seen = set()

    def _add(cite: str):
        key = cite.lower().replace(" ", "")
        if key not in seen:
            seen.add(key)
            out.append(cite)

    for m in _CITE_RE.finditer(text or ""):
        prefix = m.group(1)
        # Canonicalize the common prefixes' casing; leave others as written.
        canon = prefix.upper() if prefix.upper() in {p.upper() for p in _CODE_PREFIXES} else prefix
        number = m.group(2).rstrip(".-")     # drop a trailing sentence period/dash
        _add(f"{canon} {number}")
    for m in _R_RE.finditer(text or ""):
        # Skip R-sections already captured as part of a prefixed cite (e.g. 'CRC R337.7').
        if not any(m.group(0).lower() in c.lower() for c in out):
            _add(m.group(0))
    return out


def guess_severity(text: str) -> str:
    if _has(text, _SEV_CRITICAL):
        return "critical"
    if _has(text, _SEV_HIGH):
        return "high"
    return "medium"


def is_administrative(text: str, sections: List[str]) -> bool:
    if _has(text, _ADMIN_HINTS):
        return True
    return not sections      # no code section cited → almost certainly admin


def guess_status(text: str) -> str:
    """Info/clarification requests map to needs_review; concrete violations to
    non_compliant. The reviewer corrects the borderline ones."""
    if _has(text, _NONCOMPLY):
        return "non_compliant"
    if _has(text, _INFO_REQUEST):
        return "needs_review"
    return "non_compliant"


def guess_objectivity(text: str) -> str:
    """hard = a measurable/numeric requirement; soft = judgment."""
    return "hard" if _MEASURABLE.search(text or "") else "soft"


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-") or "x"


def split_items(text: str) -> List[str]:
    """Split a letter into per-correction blocks on numbered markers. Falls back
    to blank-line blocks if no numbering is found."""
    text = text or ""
    marks = list(_ITEM_RE.finditer(text))
    if len(marks) >= 2:
        blocks: List[str] = []
        for i, m in enumerate(marks):
            end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
            blocks.append(text[m.start():end].strip())
        return blocks
    # fallback: paragraphs
    return [b.strip() for b in re.split(r"\n\s*\n", text) if b.strip()]


def parse_correction_text(text: str) -> List[CorrectionItem]:
    """Parse a correction-letter blob into structured, guessed items."""
    items: List[CorrectionItem] = []
    for idx, block in enumerate(split_items(text), start=1):
        num_m = _ITEM_RE.match(block)
        number = int(num_m.group(1)) if num_m else idx
        body = _ITEM_RE.sub("", block, count=1).strip()
        sections = find_sections(block)
        admin = is_administrative(body, sections)
        primary = _slug(sections[0]) if sections else "review"
        items.append(CorrectionItem(
            number=number,
            raw_text=body,
            sections=sections,
            severity=guess_severity(body),
            status=guess_status(body),
            objectivity=guess_objectivity(body),
            is_administrative=admin,
            issue_id=f"item-{number:02d}-{primary}",
        ))
    return items


# ── YAML scaffold rendering (hand-built for the review annotations) ──

def _y(s: str) -> str:
    """Quote/escape a scalar for inline YAML."""
    return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"') + '"'


def _indent_block(text: str, spaces: int) -> str:
    pad = " " * spaces
    return "\n".join(pad + line for line in (text or "").splitlines()) or (pad + "(no text)")


def render_ground_truth_yaml(items: List[CorrectionItem], meta: Dict[str, str]) -> str:
    code_items = [i for i in items if not i.is_administrative]
    admin_items = [i for i in items if i.is_administrative]

    lines: List[str] = []
    lines.append(f"# SCAFFOLD — generated by `python -m benchmarks.intake` from {meta.get('source','?')}.")
    lines.append("# This is a STARTING POINT, not ground truth. A licensed reviewer MUST:")
    lines.append("#   - verify every severity / status / objectivity GUESS")
    lines.append("#   - fill acceptance_criteria (what a correct AI finding must convey)")
    lines.append("#   - add equivalent acceptable_sections (e.g. the IBC twin of a CBC cite)")
    lines.append("#   - confirm the administrative items at the bottom are really non-code")
    lines.append("")
    lines.append("description: >")
    lines.append("  TODO: one-paragraph description of the plan set + submittal.")
    lines.append("tier: C")
    lines.append("split: dev")
    lines.append(f"source: {_y(meta.get('source',''))}")
    lines.append("input_quality: vector            # verify: vector | scanned | mixed")
    lines.append("jurisdiction:")
    lines.append(f"  state: {meta.get('state','CA')}")
    lines.append(f"  city: {meta.get('city','TODO')}")
    if meta.get("county"):
        lines.append(f"  county: {meta['county']}")
    lines.append(f"plan_type: {meta.get('plan_type','residential')}   # verify")
    lines.append("labelers: []                     # add reviewer id(s) once labeled")
    lines.append("")
    lines.append(f"# {len(code_items)} code item(s) detected, {len(admin_items)} flagged administrative.")
    lines.append("expected_findings:")
    if not code_items:
        lines.append("  []   # REVIEW: no code items detected — check the letter/parsing")
    for it in code_items:
        accs = ", ".join(_y(s) for s in it.sections) or '""  # REVIEW: add the cited section'
        lines.append(f"  - issue_id: {it.issue_id}")
        lines.append(f"    acceptable_sections: [{accs}]   # add equivalents (IBC/CRC/...) if any")
        lines.append(f"    severity: {it.severity}            # GUESS — verify")
        lines.append(f"    status: {it.status}        # GUESS — needs_review = info request")
        lines.append(f"    objectivity: {it.objectivity}              # GUESS — hard=measurable, soft=judgment")
        lines.append('    acceptance_criteria: ""    # TODO: what must a correct AI finding say?')
        lines.append("    notes: |")
        lines.append(_indent_block(it.raw_text, 6))
    lines.append("")
    lines.append("# ---- Administrative / non-code items (NOT scored). Review: delete, or if")
    lines.append("# one is actually a code requirement, move it up and add its section. ----")
    if admin_items:
        for it in admin_items:
            lines.append(f"#  [{it.number}] {it.raw_text[:100].replace(chr(10),' ')}")
    else:
        lines.append("#  (none detected)")
    lines.append("")
    lines.append("must_not_flag: []                # add sections that must NEVER fire for this plan")
    lines.append("")
    return "\n".join(lines)


# ── PDF/text loading + CLI ───────────────────────────────────

def extract_text(path: Path) -> str:
    if path.suffix.lower() == ".pdf":
        import pdfplumber
        parts: List[str] = []
        with pdfplumber.open(str(path)) as pdf:
            for page in pdf.pages:
                parts.append(page.extract_text() or "")
        return "\n".join(parts)
    return path.read_text(encoding="utf-8", errors="replace")


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="benchmarks.intake",
                                 description="Scaffold ground_truth.yaml from a correction letter.")
    ap.add_argument("letter", help="path to the correction letter (.pdf or .txt)")
    ap.add_argument("--case-id", required=True, help="benchmark case id (folder name)")
    ap.add_argument("--jurisdiction", default="CA:", help="STATE:City, e.g. CA:Los Angeles")
    ap.add_argument("--county", default="")
    ap.add_argument("--plan-type", default="residential")
    ap.add_argument("--out", default=None, help="output path (default: benchmarks/cases/<id>/ground_truth.yaml)")
    ap.add_argument("--force", action="store_true", help="overwrite an existing ground_truth.yaml")
    ap.add_argument("--print", action="store_true", help="print to stdout instead of writing")
    args = ap.parse_args(argv)

    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    letter = Path(args.letter)
    if not letter.exists():
        print(f"error: {letter} not found")
        return 1

    text = extract_text(letter)
    items = parse_correction_text(text)
    state, _, city = args.jurisdiction.partition(":")
    meta = {"source": letter.name, "state": state or "CA", "city": city or "TODO",
            "county": args.county, "plan_type": args.plan_type}
    yaml_text = render_ground_truth_yaml(items, meta)

    code = sum(1 for i in items if not i.is_administrative)
    admin = sum(1 for i in items if i.is_administrative)
    no_sec = sum(1 for i in items if not i.sections and not i.is_administrative)
    print(f"Parsed {len(items)} item(s): {code} code, {admin} administrative"
          + (f", {no_sec} code item(s) WITHOUT a detected section (review)" if no_sec else ""))

    if args.print:
        print("\n" + yaml_text)
        return 0

    out = Path(args.out) if args.out else (Path(__file__).parent / "cases" / args.case_id / "ground_truth.yaml")
    if out.exists() and not args.force:
        print(f"refusing to overwrite {out} (use --force)")
        return 1
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(yaml_text, encoding="utf-8")
    print(f"scaffold -> {out}")
    print("NEXT: a licensed reviewer verifies every GUESS, fills acceptance_criteria,")
    print("      adds plan.pdf to the case folder, then `python -m benchmarks --live-pdf`.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
