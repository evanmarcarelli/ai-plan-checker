"""Pure helpers that turn flat code chunks into structured ones.

No DB, no I/O — just deterministic transforms, so they're trivially testable
and reusable by both the ingest script and the Postgres loader.

The whole point: recover the *hierarchy* and *jurisdiction scope* that the flat
JSONL `CodeChunk` throws away, so retrieval can do ancestor expansion (the
"1004.1.1 exception only makes sense inside Chapter 10" problem) and per-
adoption scoping (so a base rule and a local amendment can't both match).
"""
from __future__ import annotations

import re
from typing import Iterable, List, Optional, Sequence, Tuple

_SANITIZE = re.compile(r"[^a-z0-9]+")


def _label(s: str) -> str:
    """Sanitize an arbitrary string into a valid ltree label ([a-z0-9_])."""
    out = _SANITIZE.sub("_", s.lower()).strip("_")
    return out or "x"


def section_to_ltree(section: str) -> str:
    """Map a code section number to an ltree path WITH chapter inheritance.

        '1004.1.1' -> 'c10.s1004.s1004_1.s1004_1_1'
        '506.2'    -> 'c5.s506.s506_2'
        'R302.1'   -> 'sr302.sr302_1'     (letter-led: no numeric chapter)
        'P/GI 2026-006' -> 'sp_gi_2026_006' (non-standard: single label)

    The chapter prefix (cN) is what lets ancestor expansion pull "Chapter 10
    Means of Egress" scope for a deeply-nested exception.
    """
    raw = (section or "").strip()
    if not raw:
        return "s_unknown"

    parts = [p for p in raw.split(".") if p.strip() != ""]
    if not parts:
        return "s_unknown"

    labels: List[str] = []
    first = parts[0].strip()
    # Numeric IBC-style sections embed their chapter: 1004 -> ch 10, 506 -> ch 5.
    if first.isdigit() and len(first) >= 3:
        labels.append(f"c{int(first) // 100}")

    cum: List[str] = []
    for p in parts:
        cum.append(p.strip())
        labels.append("s" + _label(".".join(cum)))
    return ".".join(labels)


def parent_section(section: str) -> Optional[str]:
    """'1004.1.1' -> '1004.1'; '506' -> None."""
    s = (section or "").strip()
    return s.rsplit(".", 1)[0] if "." in s else None


def ancestor_paths(path: str) -> List[str]:
    """Every prefix of an ltree path, root -> full.

        'c10.s1004.s1004_1' -> ['c10', 'c10.s1004', 'c10.s1004.s1004_1']
    Used to materialize the provision tree's interior nodes from leaf chunks."""
    labels = [l for l in (path or "").split(".") if l]
    return [".".join(labels[: i + 1]) for i in range(len(labels))]


def path_label_to_number(label: str) -> str:
    """Decode one ltree label back to a human section/chapter number.

        'c10'        -> '10'        (chapter)
        's1004_1'    -> '1004.1'
        'sr302_1'    -> 'r302.1'
    Inverse of the encoding in section_to_ltree (lossy only for the original
    punctuation, which code numbering doesn't use beyond '.')."""
    if not label:
        return ""
    if label[0] == "c" and label[1:].isdigit():
        return label[1:]
    body = label[1:] if label[0] == "s" else label
    return body.replace("_", ".")


def provision_kind(label: str, depth: int, is_leaf: bool) -> str:
    """Classify a tree node: chapter (cN), top section, or subsection.

    depth is 0-based position in the path. 'exception' isn't inferable from a
    number alone, so deep leaves are 'subsection' (a structured source can
    refine later)."""
    if label[:1] == "c" and label[1:].isdigit():
        return "chapter"
    return "section" if depth <= 1 else "subsection"


def normalize_adoption_id(jurisdiction_tag: str) -> Optional[str]:
    """Normalize a corpus jurisdiction tag into an adoption id.

        '*'              -> None        (base / applies everywhere)
        'CA'             -> 'ca'
        'CA:Los Angeles' -> 'ca:los_angeles'
    Aligns with AdoptionRecord.id in adoption/schema.py.
    """
    t = (jurisdiction_tag or "").strip()
    if not t or t == "*":
        return None
    if ":" in t:
        state, place = t.split(":", 1)
        return f"{state.strip().lower()}:{_label(place)}"
    return t.lower()


def adoption_id_for_chunk(jurisdictions: Optional[Sequence[str]]) -> Optional[str]:
    """Pick the single most-specific adoption id for a chunk (city beats state;
    a bare '*' yields None = base layer)."""
    ids = [normalize_adoption_id(j) for j in (jurisdictions or [])]
    ids = [i for i in ids if i]
    if not ids:
        return None
    specific = [i for i in ids if ":" in i]
    return (specific or ids)[0]


def most_specific_layer(jurisdictions: Optional[Sequence[str]]) -> str:
    """Pick the single most-specific RAW corpus layer tag for a chunk.

    Mirrors adoption_id_for_chunk but returns the raw tag used in
    corpus_layer_keys (NOT the normalized adoption id), because the precedence
    resolver orders provisions by those raw tags:

        ['*']                       -> '*'
        ['*', 'CA']                 -> 'CA'
        ['CA', 'CA:Los Angeles']    -> 'CA:Los Angeles'
        []                          -> '*'   (base / applies everywhere)
    """
    tags = [j for j in (jurisdictions or []) if j]
    if not tags:
        return "*"
    specific = [t for t in tags if ":" in t]
    if specific:
        return specific[0]
    non_star = [t for t in tags if t != "*"]
    return (non_star or tags)[0]


def build_context_header(
    code_short: str,
    version: str,
    ancestors: Iterable[Tuple[str, str]],
    section: str,
    heading: str = "",
) -> str:
    """Build the breadcrumb that gets indexed with each chunk so a retrieved
    exception is self-explanatory.

        '2021 IBC · §1004 Occupant Load · §1004.1.1 Areas Without Fixed Seating'
    `ancestors` is an ordered list of (number, heading) root->parent.
    """
    crumbs: List[str] = [f"{version} {code_short}".strip()]
    for num, head in ancestors:
        crumbs.append(f"§{num} {head}".strip())
    crumbs.append(f"§{section} {heading}".strip())
    # de-dupe consecutive + drop empties
    out: List[str] = []
    for c in crumbs:
        if c and (not out or out[-1] != c):
            out.append(c)
    return " · ".join(out)
