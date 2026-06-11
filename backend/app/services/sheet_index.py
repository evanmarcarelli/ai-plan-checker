"""Sheet-level identification for plan sets.

Architectural sets are organized by SHEET (A-1.0 Floor Plan, S-2 Foundation,
M-1 HVAC...), not by PDF page. Until now the pipeline treated a plan set as a
flat bag of page texts, which loses the single most useful retrieval signal a
plan checker has: "look at the structural sheets" / "what does the life-safety
sheet say". This module recovers that structure from the extracted text:

1. Per-page sheet-number detection — from the title-block corner text when
   available (high precision: the sheet number is printed there on every
   sheet), falling back to labeled "SHEET NO:" patterns in the body text.
2. Cover-sheet drawing-index parsing — the "SHEET INDEX" table on the cover
   sheet maps sheet numbers to sheet titles; we use it both to title the
   pages we matched and to validate low-confidence matches.
3. Discipline classification from the sheet-number prefix (A→architectural,
   S→structural, E→electrical...), mapped onto the same department categories
   the reviewers filter on.

Everything here is deterministic text processing — no LLM, no network — so it
adds ~0 cost and is fully unit-testable. Output feeds ExtractedPlanData.sheet_index
and the plan-library persistence layer (plan_sheets rows).
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

# ── Discipline classification ────────────────────────────────────────────
#
# Standard US sheet-numbering prefixes (NCS / common practice). Longest
# prefix wins so "FP-1" is fire_protection, not an unknown "F" + "P-1".
_PREFIX_DISCIPLINES: List[tuple] = [
    ("FP", "fire_protection"), ("FA", "fire_protection"), ("FS", "fire_protection"),
    ("LS", "life_safety"), ("EG", "life_safety"),
    ("CS", "general"), ("GN", "general"), ("GI", "general"), ("TS", "general"),
    ("AD", "architectural"), ("ID", "interiors"),
    ("ST", "structural"), ("SD", "structural"),
    ("LA", "landscape"), ("LP", "landscape"),
    ("MH", "mechanical"), ("MD", "mechanical"),
    ("EL", "electrical"), ("EP", "electrical"), ("ES", "electrical"),
    ("PL", "plumbing"), ("PD", "plumbing"),
    ("DM", "demolition"),
    ("EN", "energy"), ("T24", "energy"),
    ("A", "architectural"),
    ("S", "structural"),
    ("C", "civil"),
    ("L", "landscape"),
    ("M", "mechanical"),
    ("E", "electrical"),
    ("P", "plumbing"),
    ("F", "fire_protection"),
    ("T", "general"),     # title sheet
    ("G", "general"),
    ("I", "interiors"),
    ("D", "demolition"),
    ("Q", "equipment"),
]

# Discipline → the department category the reviewers filter on. Lets a
# department reviewer (or a retrieval query) jump straight to its sheets.
DISCIPLINE_TO_CATEGORY: Dict[str, str] = {
    "general": "building_safety",
    "architectural": "building_safety",
    "structural": "building_safety",
    "civil": "public_works",
    "landscape": "environmental",
    "mechanical": "mechanical",
    "electrical": "electrical",
    "plumbing": "plumbing",
    "fire_protection": "fire",
    "life_safety": "fire",
    "energy": "energy",
    "interiors": "accessibility",
    "demolition": "building_safety",
    "equipment": "mechanical",
}


def discipline_for_sheet_number(sheet_number: str) -> Optional[str]:
    """Map a sheet number like 'A-1.0' / 'FP101' / 'S2.1' to a discipline."""
    if not sheet_number:
        return None
    m = re.match(r"^([A-Z]+)", sheet_number.strip().upper())
    if not m:
        return None
    letters = m.group(1)
    for prefix, disc in _PREFIX_DISCIPLINES:
        if letters == prefix:
            return disc
    # Multi-letter prefix we don't know wholesale: try its first letter
    # (e.g. "AX" → architectural) but only for 2-letter prefixes; longer
    # alpha runs ("NFPA") are not sheet numbers at all.
    if len(letters) == 2:
        for prefix, disc in _PREFIX_DISCIPLINES:
            if len(prefix) == 1 and letters[0] == prefix:
                return disc
    return None


# ── Sheet-number token grammar ───────────────────────────────────────────
#
# Matches: A-1.0  A1.01  A-101  S2.1  M-1  E-101  T-1.0  G-001  CS-1  A0.0
# Rejects: NFPA 13 (4-letter prefix), IBC 1004.1 (space-separated),
#          V-B / I-A (no digits), 2021 (no letter prefix).
_SHEET_NUM_RE = re.compile(
    r"\b([A-Z]{1,3}\d{0,1}-?\d{1,3}(?:\.\d{1,2}){0,2}[A-Z]?)\b"
)

# Occupancy groups / construction types that the loose grammar would
# otherwise swallow ("R-3", "A-2", "B-1"...). A bare letter-dash-digit is only
# accepted as a sheet number when it is corroborated (labeled, in the corner
# block, or listed in the cover-sheet index).
_AMBIGUOUS_RE = re.compile(r"^[ABEFHIMRSU]-?\d$")

# Same-line only ([ \t], not \s): "TITLE SHEET\nA-1.0" in a cover-sheet
# drawing index must NOT read as a "SHEET A-1.0" label across the newline.
_SHEET_LABEL_RE = re.compile(
    r"SHEET[ \t]*(?:NO|NUMBER|#)?[ \t]*[.:#]?[ \t]*"
    r"([A-Z]{1,3}\d{0,1}-?\d{1,3}(?:\.\d{1,2}){0,2}[A-Z]?)\b",
    re.IGNORECASE,
)

_INDEX_HEADER_RE = re.compile(
    r"(?:SHEET\s+INDEX|DRAWING\s+INDEX|INDEX\s+OF\s+(?:DRAWINGS|SHEETS)|"
    r"SHEET\s+LIST|LIST\s+OF\s+DRAWINGS)",
    re.IGNORECASE,
)

# A drawing-index line: "A-1.0  FLOOR PLAN" / "S-1 - FOUNDATION PLAN"
_INDEX_LINE_RE = re.compile(
    r"^\s*([A-Z]{1,3}\d{0,1}-?\d{1,3}(?:\.\d{1,2}){0,2}[A-Z]?)\s*[-–—.:]?\s+"
    r"([A-Z0-9][A-Za-z0-9 ,.&/()'\"-]{2,80})\s*$"
)


def _looks_like_sheet_number(token: str) -> bool:
    """Reject grammar matches that are clearly something else."""
    t = token.strip().upper()
    if not _SHEET_NUM_RE.fullmatch(t):
        return False
    # Pure numbers with a letter suffix ("13D") are not sheet numbers.
    if not re.match(r"^[A-Z]", t):
        return False
    return True


def parse_cover_sheet_index(pages: Dict[int, str], max_pages: int = 5) -> Dict[str, str]:
    """Parse the SHEET INDEX table off the cover/title sheet.

    Returns {sheet_number: sheet_title}. Scans the first `max_pages` pages
    for an index header, then collects subsequent lines that look like
    "<sheet-number> <title>". Stops a run after 8 consecutive non-matching
    lines (the end of the table).
    """
    index: Dict[str, str] = {}
    for page_num in sorted(pages)[:max_pages]:
        text = pages.get(page_num) or ""
        m = _INDEX_HEADER_RE.search(text)
        if not m:
            continue
        misses = 0
        for line in text[m.end():].splitlines():
            lm = _INDEX_LINE_RE.match(line)
            if lm:
                num = lm.group(1).upper()
                title = lm.group(2).strip().rstrip(".")
                if _looks_like_sheet_number(num) and num not in index:
                    # An index entry corroborates even ambiguous tokens
                    # (legit residential sets do use "A-1", "A-2"...), but an
                    # occupancy-group-looking token needs a drawing-ish title
                    # to be believed ("R-3 SECOND FLOOR PLAN" yes,
                    # "R-3 OCCUPANCY" no).
                    if _AMBIGUOUS_RE.match(num) and re.search(
                        r"\b(OCCUPANC|GROUP|ZONE|TYPE)\b", title, re.IGNORECASE
                    ):
                        continue
                    index[num] = title
                misses = 0
            else:
                if line.strip():
                    misses += 1
                if misses > 8 and index:
                    break
    return index


def _candidates_from_text(text: str) -> List[tuple]:
    """All (token, labeled) sheet-number candidates in a text blob."""
    out: List[tuple] = []
    for m in _SHEET_LABEL_RE.finditer(text):
        tok = m.group(1).upper()
        if _looks_like_sheet_number(tok):
            out.append((tok, True))
    for m in _SHEET_NUM_RE.finditer(text.upper()):
        tok = m.group(1)
        if _looks_like_sheet_number(tok):
            out.append((tok, False))
    return out


def detect_page_sheet_number(
    page_text: str,
    corner_text: Optional[str],
    cover_index: Dict[str, str],
) -> Optional[Dict[str, Any]]:
    """Best sheet-number guess for one page.

    Priority:
      1. Labeled "SHEET NO: X" anywhere on the page          (conf 0.95)
      2. Token in the title-block corner text                 (conf 0.85)
      3. Unlabeled body token that the cover index also lists (conf 0.7)
    Ambiguous tokens (occupancy-group lookalikes like "R-3") are only
    accepted when corroborated by the cover index.
    """
    def _accept(tok: str, conf: float, source: str) -> Optional[Dict[str, Any]]:
        if _AMBIGUOUS_RE.match(tok) and tok not in cover_index:
            return None
        return {
            "sheet_number": tok,
            "confidence": conf,
            "source": source,
            "sheet_title": cover_index.get(tok),
            "discipline": discipline_for_sheet_number(tok),
        }

    # 1. Labeled match (page body or corner).
    for blob, source in ((corner_text or "", "title_block"), (page_text or "", "label")):
        m = _SHEET_LABEL_RE.search(blob)
        if m and _looks_like_sheet_number(m.group(1).upper()):
            hit = _accept(m.group(1).upper(), 0.95, source)
            if hit:
                return hit

    # 2. Corner-text token (title blocks print the sheet number standalone).
    if corner_text:
        seen: List[str] = []
        for tok, _labeled in _candidates_from_text(corner_text):
            if tok not in seen:
                seen.append(tok)
        # Prefer a token the cover index knows; else the LAST token in the
        # corner block (sheet number is conventionally the bottom-most line).
        for tok in seen:
            if tok in cover_index:
                hit = _accept(tok, 0.9, "title_block")
                if hit:
                    return hit
        for tok in reversed(seen):
            hit = _accept(tok, 0.85, "title_block")
            if hit:
                return hit

    # 3. Body token confirmed by the cover index.
    if page_text and cover_index:
        for tok, _labeled in _candidates_from_text(page_text):
            if tok in cover_index:
                hit = _accept(tok, 0.7, "index_match")
                if hit:
                    return hit

    return None


def build_sheet_index(
    pages: Dict[int, str],
    page_corners: Optional[Dict[int, str]] = None,
) -> List[Dict[str, Any]]:
    """Build the per-page sheet index for a plan set.

    Returns one record per page (whether or not a sheet number was found):
      {page_number, sheet_number, sheet_title, discipline, category,
       source, confidence}
    Pages with no detected sheet number get sheet_number=None so consumers
    can still see extraction coverage.
    """
    page_corners = page_corners or {}
    cover_index = parse_cover_sheet_index(pages)

    records: List[Dict[str, Any]] = []
    for page_num in sorted(pages):
        hit = detect_page_sheet_number(
            pages.get(page_num) or "", page_corners.get(page_num), cover_index
        )
        rec: Dict[str, Any] = {
            "page_number": page_num,
            "sheet_number": None,
            "sheet_title": None,
            "discipline": None,
            "category": None,
            "source": None,
            "confidence": 0.0,
        }
        if hit:
            rec.update(hit)
            if rec.get("discipline"):
                rec["category"] = DISCIPLINE_TO_CATEGORY.get(rec["discipline"])
        records.append(rec)

    # Index entries whose sheet we never matched to a page are still useful
    # (they prove the sheet exists in the set). Mark matched entries.
    matched = {r["sheet_number"] for r in records if r["sheet_number"]}
    for num, title in cover_index.items():
        if num not in matched:
            records.append({
                "page_number": None,
                "sheet_number": num,
                "sheet_title": title,
                "discipline": discipline_for_sheet_number(num),
                "category": DISCIPLINE_TO_CATEGORY.get(
                    discipline_for_sheet_number(num) or ""
                ),
                "source": "index_only",
                "confidence": 0.5,
            })
    return records


def summarize_sheet_index(sheet_index: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Compact stats for logs / extraction_stats."""
    on_pages = [r for r in sheet_index if r.get("page_number") is not None]
    identified = [r for r in on_pages if r.get("sheet_number")]
    disciplines: Dict[str, int] = {}
    for r in identified:
        d = r.get("discipline") or "unknown"
        disciplines[d] = disciplines.get(d, 0) + 1
    return {
        "pages": len(on_pages),
        "pages_with_sheet_number": len(identified),
        "index_only_sheets": sum(1 for r in sheet_index if r.get("source") == "index_only"),
        "disciplines": disciplines,
    }
