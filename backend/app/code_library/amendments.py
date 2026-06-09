"""Local-amendment resolution: base provision text  ⊕  jurisdiction deltas.

A jurisdiction adopts a base edition then strikes/replaces/adds specific
provisions (LA amends the CBC, which amends the IBC). This computes the
*effective* text for a provision in a given adoption as of a date, applying
only amendments that have passed human review (needs_review=False) — never
mutating the immutable base.

The apply step is a pure function so it's fully unit-testable without a DB;
resolve_provision() wires it to the store.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ResolvedProvision:
    """The effective text of a provision after local amendments."""
    text: Optional[str]                       # None => struck / deleted
    base_text: Optional[str]
    applied: List[str] = field(default_factory=list)   # ordinance cites applied
    deleted: bool = False                     # section removed by the AHJ


def _live(amendments: List[Dict[str, Any]], as_of: Optional[str]) -> List[Dict[str, Any]]:
    """Amendments that are in force: reviewed (not needs_review) and effective
    on/before as_of (if a cutoff is given). Ordered by effective_date so later
    ordinances win."""
    out = []
    for a in amendments:
        if a.get("needs_review", True):
            continue                          # human gate: unreviewed deltas never apply
        eff = a.get("effective_date")
        if as_of and eff and str(eff) > str(as_of):
            continue                          # not yet effective for this permit date
        out.append(a)
    return sorted(out, key=lambda a: str(a.get("effective_date") or ""))


def apply_amendments(
    base_text: Optional[str],
    amendments: List[Dict[str, Any]],
    as_of: Optional[str] = None,
) -> ResolvedProvision:
    """Apply strike/replace/add/delete_section deltas to base text. Pure."""
    text = base_text
    applied: List[str] = []
    deleted = False
    for a in _live(amendments, as_of):
        op = a.get("op")
        if op == "replace":
            text = a.get("new_text")
        elif op == "strike":
            text = None
        elif op == "delete_section":
            text, deleted = None, True
        elif op == "add":
            extra = a.get("new_text") or ""
            text = f"{text}\n{extra}".strip() if text else extra
        else:
            continue                          # unknown op: ignore, don't corrupt text
        applied.append(a.get("ordinance_cite", "?"))
    return ResolvedProvision(text=text, base_text=base_text, applied=applied, deleted=deleted)


def resolve_provision(
    edition_id: str,
    path: str,
    adoption_id: Optional[str],
    as_of: Optional[str] = None,
) -> ResolvedProvision:
    """Fetch base provision + this adoption's amendments and resolve. Falls
    back to base-only (no amendments) if the store/migration isn't available."""
    from app.code_library import store
    base = store.fetch_provision(edition_id, path) or {}
    base_text = base.get("text")
    amendments = store.fetch_amendments(adoption_id, path) if adoption_id else []
    return apply_amendments(base_text, amendments, as_of)
