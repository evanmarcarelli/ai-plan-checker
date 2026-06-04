"""Section → CodeChunk transformation.

Each RawSection coming out of a scraper becomes one or more dict-shaped
CodeChunks ready to JSON-serialize. The shape matches what
corpus_loader.CodeChunk expects, so the existing BM25 retriever picks
them up with no further plumbing.

Two non-trivial bits live here:

1. classify_category(): a keyword classifier that maps the section's
   title + breadcrumb to one of the ten categories the department
   reviewers filter on. Without this, every scraped chunk would be
   "general" and the wrong department would review it.

2. split_oversize_section(): some municipal sections are pages long.
   Anthropic prompt caching is happiest with smaller blocks and the
   model's working memory is finite, so anything over ~SOFT_MAX_CHARS
   gets split on paragraph boundaries.
"""
from __future__ import annotations

import re
from typing import Dict, Iterable, List, Optional

from app.code_library.ingest.base import IngestTarget, RawSection


# Soft cap on chunk text size. Sections longer than this are split on
# paragraph boundaries. Keeps any single chunk under roughly 2k tokens.
SOFT_MAX_CHARS = 6000

# Keyword tables, applied in priority order. First match wins so the most
# specific categories (fire, electrical) are checked before the catch-all
# building_safety. Lowercased on lookup.
#
# Keywords are matched with WORD BOUNDARIES, not substring. "fire" must
# not match "fuel-fired" or "firearm". The classifier uses a precompiled
# regex per keyword. Multi-word keywords ("fire department") match as a
# phrase with whitespace tolerance.
#
# Environmental comes BEFORE fire because WUI/wildland is more naturally
# an environmental finding than a fire finding (it's about ember-resistant
# construction, defensible space, vegetation), even though it relates to
# fire risk.
_CATEGORY_RULES: List[tuple] = [
    ("environmental", [
        "wildland-urban interface", "wildland", "wui", "ember-resistant",
        "ember", "ignition-resistant", "swppp", "stormwater", "npdes",
        "asbestos", "lead-safe", "ceqa", "defensible space", "hazardous",
        "chapter 7a",
    ]),
    ("fire", [
        "fire", "sprinkler", "smoke alarm", "smoke detector", "alarm",
        "extinguisher", "fire department", "egress", "evacuation",
        "fire-resistance", "fire flow", "hydrant", "fire access",
    ]),
    ("electrical", [
        "electrical", "wiring", "conductor", "gfci", "afci", "receptacle",
        "circuit", "panel", "service entrance", "grounding", "ampacity",
        "transformer", "luminaire", "lighting power",
    ]),
    ("plumbing", [
        "plumbing", "drain", "vent", "fixture", "backflow", "water closet",
        "lavatory", "shower", "potable water", "sewer", "trap", "gas piping",
        "water heater",
    ]),
    ("mechanical", [
        "mechanical", "hvac", "ventilation", "duct", "exhaust", "combustion air",
        "refrigerant", "boiler", "kitchen hood", "indoor air",
    ]),
    ("accessibility", [
        "accessibility", "accessible route", "wheelchair", "ada", "barrier-free",
        "grab bar", "ramp", "tactile", "braille", "path of travel",
        "cbc 11b", "chapter 11a", "chapter 11b",
    ]),
    ("energy", [
        "energy", "title 24", "calgreen", "insulation", "u-factor", "shgc",
        "solar", "photovoltaic", "ev charging", "low-flow",
    ]),
    ("zoning", [
        "zoning", "setback", "yard", "floor area ratio", "far", "height limit",
        "lot coverage", "use permit", "variance", "overlay district",
        "hillside", "coastal", "historic", "adu", "accessory dwelling",
    ]),
    ("public_works", [
        "public works", "right-of-way", "encroachment", "driveway", "sidewalk",
        "curb cut", "grading", "drainage", "utility connection", "easement",
    ]),
    ("building_safety", [
        "occupancy", "construction type", "structural", "seismic", "wind load",
        "live load", "foundation", "ceiling height", "exit", "corridor",
        "stair", "tread", "riser", "guard", "handrail", "building", "framing",
        "egress door",
    ]),
]


# Compile keyword regexes once. \b word boundaries so "fire" matches
# "fire department" but NOT "fuel-fired". For multi-word phrases the
# internal spaces stay literal.
_COMPILED_RULES: List[tuple] = [
    (cat, [re.compile(r"\b" + re.escape(kw) + r"\b", re.IGNORECASE) for kw in kws])
    for cat, kws in _CATEGORY_RULES
]


def classify_category(title: str, breadcrumb: List[str], text: str) -> str:
    """Best-effort category for routing to a department reviewer.

    Strategy: combine the title and breadcrumb (where the city already
    organized the section by topic) plus the first ~500 chars of text;
    walk the priority-ordered keyword list; first match wins. Word
    boundaries are enforced so "fire" does not match "fuel-fired".
    Falls back to 'building_safety' as the generic structural/code default.
    """
    haystack = " ".join([title or ""] + (breadcrumb or []))
    body_sample = (text or "")[:500]
    combined = haystack + " " + body_sample
    for category, patterns in _COMPILED_RULES:
        if any(p.search(combined) for p in patterns):
            return category
    return "building_safety"


# ─────────────────────────────────────────────────────────────────────
# Chunking
# ─────────────────────────────────────────────────────────────────────

_SECTION_NUM_RE = re.compile(r"[A-Z0-9]+(?:\.[A-Z0-9]+)*", re.IGNORECASE)
_WHITESPACE_RE = re.compile(r"[ \t]+")
_BLANK_LINES_RE = re.compile(r"\n{3,}")


def _normalize_text(s: str) -> str:
    """Light cleanup. Scrapers vary in how clean their text is."""
    s = s.replace("\xa0", " ")
    s = _WHITESPACE_RE.sub(" ", s)
    s = _BLANK_LINES_RE.sub("\n\n", s)
    return s.strip()


def _make_tags(breadcrumb: List[str], extra: Optional[List[str]]) -> List[str]:
    """Tags help the BM25 retriever match queries that mention things like
    'hillside' or 'WUI' or 'ADU' which appear in the breadcrumb but not
    necessarily in the section body."""
    out: List[str] = []
    seen = set()
    for crumb in (breadcrumb or [])[-3:]:   # last few are most specific
        for tok in re.split(r"[\s/\-]+", crumb.lower()):
            tok = tok.strip()
            if len(tok) >= 4 and tok not in seen:
                out.append(tok)
                seen.add(tok)
            if len(out) >= 8:
                break
    for tag in (extra or []):
        tag = tag.lower().strip()
        if tag and tag not in seen:
            out.append(tag)
            seen.add(tag)
    return out


def _hard_wrap(text: str, limit: int) -> List[str]:
    """Last-resort splitter for a block with no paragraph breaks (common in
    PDF-extracted text). Splits on line, then sentence, then raw character
    boundaries so no single chunk exceeds ~limit. Without this, PDF code text
    that pdfplumber joins with single newlines would yield one giant chunk
    that matches every BM25 query and cites nothing precisely."""
    if len(text) <= limit:
        return [text]
    out: List[str] = []
    buf = ""
    # Prefer line boundaries, then sentence ends, as soft break points.
    units = re.split(r"(?<=\n)|(?<=[.;:]\s)", text)
    for u in units:
        while len(u) > limit:                 # a single monster unit
            out.append(u[:limit])
            u = u[limit:]
        if len(buf) + len(u) > limit and buf:
            out.append(buf)
            buf = ""
        buf += u
    if buf.strip():
        out.append(buf)
    return [c.strip() for c in out if c.strip()]


def _split_oversize(text: str) -> List[str]:
    """Split a too-long section body. First on blank-line paragraph
    boundaries; any resulting part that is still oversize (e.g. PDF text with
    no blank lines) is hard-wrapped so every chunk stays near SOFT_MAX_CHARS."""
    if len(text) <= SOFT_MAX_CHARS:
        return [text]
    paragraphs = re.split(r"\n\s*\n", text)
    chunks: List[str] = []
    buf: List[str] = []
    buf_len = 0

    def flush():
        if buf:
            chunks.append("\n\n".join(buf).strip())

    for p in paragraphs:
        # A single paragraph bigger than the cap (PDF with no blank lines):
        # flush what we have, then hard-wrap the monster paragraph.
        if len(p) > SOFT_MAX_CHARS:
            flush()
            buf, buf_len = [], 0
            chunks.extend(_hard_wrap(p, SOFT_MAX_CHARS))
            continue
        p_len = len(p) + 2
        if buf_len + p_len > SOFT_MAX_CHARS and buf:
            flush()
            buf, buf_len = [], 0
        buf.append(p)
        buf_len += p_len
    flush()
    return [c for c in chunks if c.strip()]


def chunk_section(section: RawSection, target: IngestTarget) -> List[Dict]:
    """Turn one RawSection into one or more JSONL-ready dicts."""
    body = _normalize_text(section.text or "")
    if not body:
        return []   # empty sections are noise

    title = (section.title or "").strip() or section.section_number
    section_number = (section.section_number or "").strip() or "(unnumbered)"
    category = classify_category(title, section.breadcrumb or [], body)
    tags = _make_tags(section.breadcrumb, section.extra_tags)

    parts = _split_oversize(body)
    chunks: List[Dict] = []
    for i, part in enumerate(parts):
        suffix = f"-{i+1}" if len(parts) > 1 else ""
        chunk_id = f"{target.code_short}-{section_number}{suffix}".lower()
        chunks.append({
            "chunk_id": chunk_id,
            "code_name": target.code_name,
            "code_short": target.code_short,
            "version": target.version,
            "section": section_number,
            "title": title,
            "category": category,
            "jurisdictions": list(target.jurisdictions),
            "text": part,
            "tags": tags,
        })
    return chunks


def chunk_many(
    sections: Iterable[RawSection],
    target: IngestTarget,
) -> Iterable[Dict]:
    """Convenience: stream chunks from a stream of sections."""
    for s in sections:
        for chunk in chunk_section(s, target):
            yield chunk
