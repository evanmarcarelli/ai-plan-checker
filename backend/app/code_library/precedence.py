"""Legal-precedence resolution: given the applicable code provisions for a plan
across jurisdiction layers (model / state / county / city / overlay), decide
WHICH ONE GOVERNS when they conflict — and record why.

This is the layer the system was missing. It previously retrieved base + state
+ local provisions together and handed them all to the LLM with no rule for
which controls. The four California rules encoded here:

  (a) Standards       -> the MORE RESTRICTIVE provision governs; the locally
                         adopted amendment is operative (Health & Safety 17958.5).
  (b) Zoning/land use -> the LOCAL ordinance governs, EXCEPT where a state
                         statute preempts it (ADU, SB 9, density bonus, Coastal Act).
  (c) Overlays        -> additive; they STACK on top, never replace.
  (d) Federal ADA     -> independent; the stricter of ADA vs CBC 11A/11B governs.

Pure: no LLM, no network, no DB. Storage-agnostic — it consumes a flat list of
CodeRequirement (each carrying a `layer_key`) plus a PrecedencePolicy, so the
same algorithm works on the in-memory corpus today and on resolved structured
provisions (v2) tomorrow.

When the system cannot SAFELY tell which provision is more restrictive (missing
numbers or an ambiguous min/max direction), it flags the topic `needs_review`
and keeps BOTH provisions rather than guessing — the same conservative posture
as the citation gate.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Set, Tuple

from app.code_library.deterministic.value_check import _first_number
from app.models.schemas import CodeRequirement
from app.utils.logger import get_logger

logger = get_logger(__name__)


# --- Topic classification -------------------------------------------------

# Overlay layer tags that STACK (additive) rather than compete with the base.
_OVERLAY_LAYERS = {"CA:Coastal"}

# CodeRequirement.category values that are accessibility (ADA vs CBC 11A/11B):
# the stricter of the two governs and BOTH are retained.
_ACCESSIBILITY_CATEGORIES = {"accessibility"}

# Zoning / land-use categories: local governs unless a state carve-out preempts.
_ZONING_CATEGORIES = {"zoning", "planning", "planning_zoning"}

# CodeRequirement.category (department category) -> amendment_relations
# discipline key in the adoption map. Bridges the building_safety<->building and
# energy<->green naming gap so a relation authored per discipline is found by a
# requirement carrying the department category.
_CATEGORY_TO_DISCIPLINE = {
    "building_safety": "building",
    "fire": "fire",
    "electrical": "electrical",
    "plumbing": "plumbing",
    "mechanical": "mechanical",
    "accessibility": "accessibility",
    "energy": "green",
    "zoning": "zoning",
    "public_works": "public_works",
    "environmental": "environmental",
}

# Direction of stringency for numeric provisions. A MINIMUM requirement is
# stricter when the number is LARGER (egress width, fixture count, R-value); a
# MAXIMUM is stricter when SMALLER (allowable area, height, FAR). Kept small and
# explicit on purpose — an unclassified provision falls to needs_review rather
# than risk picking the wrong governor.
_MIN_IS_STRICTER = {
    "egress", "width", "fixture", "ventilation", "r-value", "r value",
    "setback", "clearance", "illumination", "exit", "exits", "landing",
    "headroom", "riser", "tread", "guard", "handrail", "outdoor air",
    "minimum",
}
_MAX_IS_STRICTER = {
    "area", "height", "stories", "story", "far", "floor area ratio",
    "coverage", "travel distance", "occupant load", "dead end", "dead-end",
    "common path", "slope", "maximum",
}

# LA building/residential codes prefix their sections with the chapter number
# (91. = LABC, 91.x residential, etc.). Strip it so a base "1011.5" and a local
# "91.1011.5" collapse to the same topic.
_LA_PREFIX_RE = re.compile(r"^9\d\.")

# Carve-out activation signals (cheap text scan of the plan).
_ADU_RE = re.compile(r"\b(adu|accessory dwelling|junior adu|jadu)\b", re.IGNORECASE)
_SB9_RE = re.compile(r"\b(sb[- ]?9|urban lot split|two[- ]unit)\b", re.IGNORECASE)
_DENSITY_BONUS_RE = re.compile(r"\bdensity bonus\b", re.IGNORECASE)


# --- Data classes ---------------------------------------------------------

@dataclass
class GoverningDecision:
    """The resolved governing provision for one topic + the audit trail."""
    topic: str
    governing: CodeRequirement
    governing_layer: str
    basis: str               # single_layer | more_restrictive | local_replaces |
                             # local_governs | state_preempts_local | overlay_stacks | ada_independent
    rationale: str
    superseded: List[CodeRequirement] = field(default_factory=list)
    superseded_layers: List[str] = field(default_factory=list)
    needs_review: bool = False
    members: List[CodeRequirement] = field(default_factory=list)


@dataclass
class PrecedencePolicy:
    """Everything resolve_precedence needs to adjudicate, derived once per job."""
    layer_order: List[str] = field(default_factory=list)        # MOST-specific first
    relations: Dict[str, str] = field(default_factory=dict)     # discipline -> relationship
    preemptions: Dict[str, Dict[str, str]] = field(default_factory=dict)  # carve-out id -> meta
    active_carveouts: Set[str] = field(default_factory=set)     # carve-outs LIVE for THIS project


# --- Policy construction --------------------------------------------------

def build_policy(resolved_stack, *, state: Optional[str] = None,
                 site_context=None, plan_data=None) -> PrecedencePolicy:
    """Turn a ResolvedStack + project signals into a PrecedencePolicy.

    Centralises the layer ordering and the active-carve-out computation so the
    workflow integration stays a couple of lines.
    """
    layer_order: List[str] = []
    relations: Dict[str, str] = {}
    preemptions: Dict[str, Dict[str, str]] = {}
    if resolved_stack is not None:
        # corpus_layer_keys are least->most specific (["*","CA","CA:LA"]); we
        # want most-specific first so members[0] is the most-local provision.
        layer_order = list(reversed(list(getattr(resolved_stack, "corpus_layer_keys", []) or [])))
        relations = dict(getattr(resolved_stack, "amendment_relations", {}) or {})
        preemptions = dict(getattr(resolved_stack, "preemptions", {}) or {})
    active = _active_carveouts(preemptions, site_context=site_context, plan_data=plan_data)
    return PrecedencePolicy(
        layer_order=layer_order, relations=relations,
        preemptions=preemptions, active_carveouts=active,
    )


def _active_carveouts(preemptions, *, site_context=None, plan_data=None) -> Set[str]:
    """Which preemption carve-outs are LIVE for this project. Conservative —
    only activates on a clear signal; default off means local governs (the safe
    failure, i.e. status-quo behaviour)."""
    active: Set[str] = set()
    if not preemptions:
        return active
    # Coastal: authoritative GIS overlay signal (the same one the workflow uses
    # to add the CA:Coastal layer).
    overlays = ((site_context or {}).get("overlays") if isinstance(site_context, dict) else None) or {}
    coastal = overlays.get("coastal") if isinstance(overlays, dict) else None
    if isinstance(coastal, dict) and coastal.get("in_zone") and "coastal_act" in preemptions:
        active.add("coastal_act")
    # ADU / SB 9 / density bonus: cheap scan of the plan text.
    blob = _plan_text_blob(plan_data)
    if blob:
        if "adu" in preemptions and _ADU_RE.search(blob):
            active.add("adu")
        if "sb9" in preemptions and _SB9_RE.search(blob):
            active.add("sb9")
        if "density_bonus" in preemptions and _DENSITY_BONUS_RE.search(blob):
            active.add("density_bonus")
    return active


def _plan_text_blob(plan_data, *, cap: int = 20000) -> str:
    if plan_data is None:
        return ""
    parts: List[str] = []
    for attr in ("project_name", "project_address", "occupancy_type"):
        v = getattr(plan_data, attr, None)
        if v:
            parts.append(str(v))
    pages = getattr(plan_data, "raw_text_by_page", None) or {}
    if isinstance(pages, dict):
        for _pn, txt in pages.items():
            if txt:
                parts.append(txt)
            if sum(len(p) for p in parts) > cap:
                break
    return " ".join(parts)[:cap]


# --- Core resolution ------------------------------------------------------

def resolve_precedence(
    requirements: Sequence[CodeRequirement],
    policy: PrecedencePolicy,
    *,
    plan_data=None,
    adoption_id: Optional[str] = None,
) -> List[GoverningDecision]:
    """Group requirements by topic and decide which layer governs each."""
    groups: Dict[Tuple[str, str], List[CodeRequirement]] = {}
    order: List[Tuple[str, str]] = []
    for r in requirements:
        k = _topic_key(r)
        if k not in groups:
            groups[k] = []
            order.append(k)
        groups[k].append(r)

    decisions: List[GoverningDecision] = []
    for k in order:
        members = sorted(
            groups[k],
            key=lambda r: _specificity(getattr(r, "layer_key", None) or "*", policy.layer_order),
        )
        decisions.append(_decide_topic(f"{k[0]}:{k[1]}", members, policy))
    return decisions


def _decide_topic(topic: str, members: List[CodeRequirement],
                  policy: PrecedencePolicy) -> GoverningDecision:
    local = members[0]
    base = members[-1]
    category = getattr(local, "category", "") or "general"
    local_layer = getattr(local, "layer_key", None) or "*"

    def mk(governing, basis, rationale, superseded=None, needs_review=False):
        superseded = superseded or []
        return GoverningDecision(
            topic=topic, governing=governing,
            governing_layer=getattr(governing, "layer_key", None) or "*",
            basis=basis, rationale=rationale,
            superseded=superseded, superseded_layers=_unique_layers(superseded),
            needs_review=needs_review, members=members,
        )

    # Trivial: a single applicable provision.
    if len(members) == 1:
        return mk(local, "single_layer", "Only one applicable provision for this topic.")

    relation = _relation_for(category, policy)

    # (c) Overlays stack: additive, nothing superseded.
    if relation == "overlay" or _is_overlay_layer(local_layer):
        return mk(local, "overlay_stacks",
                  "Overlay layer — additive requirements that stack on top of the base; "
                  "none superseded.")

    # (d) Accessibility: stricter of ADA vs CBC 11A/11B; BOTH retained.
    if category in _ACCESSIBILITY_CATEGORIES:
        gov, _sup, why, nr = stricter_of(members)
        return mk(gov, "ada_independent",
                  "ADA is an independent federal overlay; the stricter of ADA vs CBC "
                  "11A/11B governs. " + why, superseded=[], needs_review=nr)

    # (b) Zoning: local governs unless a state carve-out preempts.
    if category in _ZONING_CATEGORIES:
        carve = _matching_carveout(policy)
        if carve:
            _cid, meta = carve
            gov = base if base is not local else local
            return mk(gov, "state_preempts_local",
                      f"State preemption — {meta.get('statute', '')}: {meta.get('summary', '')} "
                      f"This overrides the local zoning provision.",
                      superseded=[m for m in members if m is not gov])
        return mk(local, "local_governs",
                  "Local zoning ordinance governs land use; no state preemption "
                  "triggered for this project.",
                  superseded=[m for m in members if m is not local])

    # (a) Standards.
    if relation == "replaces":
        return mk(local, "local_replaces",
                  "Local amendment replaces the base provision for this jurisdiction.",
                  superseded=[m for m in members if m is not local])
    if relation == "adds":
        return mk(local, "overlay_stacks",
                  "Local amendment adds requirements on top of the base; none superseded.")
    # default: more_restrictive governs.
    gov, sup, why, nr = stricter_of(members)
    return mk(gov, "more_restrictive", why, superseded=sup, needs_review=nr)


def stricter_of(
    members: List[CodeRequirement],
) -> Tuple[CodeRequirement, List[CodeRequirement], str, bool]:
    """Return (governing, superseded, rationale, needs_review).

    Picks the more-restrictive numeric provision when BOTH the numbers and the
    min/max direction are clear; otherwise flags needs_review (keeping all
    members, governor = most-specific) so a human adjudicates rather than the
    system guessing.
    """
    have = [(m, _req_number(m)) for m in members]
    have = [(m, n) for m, n in have if n is not None]
    direction = next((d for d in (_direction(m) for m in members) if d), None)

    if len(have) < 2 or direction is None:
        gov = members[0]
        rationale = (
            "Provisions across layers could not be compared numerically (missing "
            "values or ambiguous min/max direction) — both retained for human "
            "review; the more-restrictive provision governs."
        )
        return gov, [m for m in members if m is not gov], rationale, True

    if direction == "min":
        gov, val = max(have, key=lambda t: t[1])
        word = "largest minimum"
    else:
        gov, val = min(have, key=lambda t: t[1])
        word = "smallest maximum"
    superseded = [m for m in members if m is not gov]
    rationale = (
        f"More-restrictive governs (H&S 17958.5): the {word} value ({val:,.0f}) "
        f"controls across {len(members)} layered provision(s)."
    )
    return gov, superseded, rationale, False


# --- Helpers --------------------------------------------------------------

def _topic_key(req: CodeRequirement) -> Tuple[str, str]:
    cat = getattr(req, "category", "") or "general"
    root = _section_root(getattr(req, "section", "") or "")
    if not root:
        # No parseable section -> don't risk merging unrelated provisions; make
        # the topic unique so it resolves as single_layer.
        return (cat, f"__uniq__:{getattr(req, 'code_id', '') or id(req)}")
    return (cat, root)


def _section_root(section: str) -> str:
    s = (section or "").strip()
    if not s:
        return ""
    s = _LA_PREFIX_RE.sub("", s)                     # 91.1011.5 -> 1011.5
    parts = [p for p in s.split(".") if p != ""]
    return ".".join(parts[:2])                        # first two dotted components


def _specificity(layer: str, layer_order: List[str]) -> int:
    """Lower = MORE specific (sorts first)."""
    if layer in layer_order:
        return layer_order.index(layer)
    base = len(layer_order)
    if not layer or layer == "*":
        return base + 2                               # base / global, least specific
    if ":" in layer:
        return base                                   # jurisdiction-specific
    return base + 1                                   # state-ish


def _relation_for(category: str, policy: PrecedencePolicy) -> str:
    if category in policy.relations:
        return policy.relations[category]
    disc = _CATEGORY_TO_DISCIPLINE.get(category)
    if disc and disc in policy.relations:
        return policy.relations[disc]
    return ""


def _is_overlay_layer(layer: str) -> bool:
    return layer in _OVERLAY_LAYERS


def _matching_carveout(policy: PrecedencePolicy) -> Optional[Tuple[str, Dict[str, str]]]:
    for cid in policy.active_carveouts:
        meta = policy.preemptions.get(cid)
        if meta and meta.get("topic", "zoning") == "zoning":
            return cid, meta
    return None


def _req_number(req: CodeRequirement) -> Optional[float]:
    mn = getattr(req, "min_value", None)
    mx = getattr(req, "max_value", None)
    if isinstance(mn, (int, float)):
        return float(mn)
    if isinstance(mx, (int, float)):
        return float(mx)
    return _first_number(getattr(req, "description", None), getattr(req, "full_text", None))


def _direction(req: CodeRequirement) -> Optional[str]:
    """'min' (larger is stricter) | 'max' (smaller is stricter) | None (unknown)."""
    if getattr(req, "min_value", None) is not None and getattr(req, "max_value", None) is None:
        return "min"
    if getattr(req, "max_value", None) is not None and getattr(req, "min_value", None) is None:
        return "max"
    hay = (
        f"{getattr(req, 'category', '')} {getattr(req, 'description', '')} "
        f"{getattr(req, 'section', '')}"
    ).lower()
    is_min = any(k in hay for k in _MIN_IS_STRICTER)
    is_max = any(k in hay for k in _MAX_IS_STRICTER)
    if is_min and not is_max:
        return "min"
    if is_max and not is_min:
        return "max"
    return None


def _unique_layers(reqs: Sequence[CodeRequirement]) -> List[str]:
    out: List[str] = []
    for r in reqs:
        lk = getattr(r, "layer_key", None) or "*"
        if lk not in out:
            out.append(lk)
    return out


# --- Consumption helpers (for the workflow + reviewers) -------------------

def index_by_code_id(decisions: Sequence[GoverningDecision]) -> Dict[str, GoverningDecision]:
    """Map every member's code_id -> its GoverningDecision (governing AND
    superseded) so any finding can look up which law governs its topic."""
    idx: Dict[str, GoverningDecision] = {}
    for d in decisions:
        for m in (d.members or [d.governing]):
            cid = getattr(m, "code_id", "") or ""
            if cid:
                idx.setdefault(cid, d)
    return idx


def governing_note(decision: GoverningDecision) -> str:
    """One-line governing-law note for a requirement (reviewer prompt)."""
    return (
        f"GOVERNED BY {decision.governing_layer} ({decision.basis}): "
        f"{decision.rationale}"
    )


def summarize(decisions: Sequence[GoverningDecision]) -> Dict[str, int]:
    return {
        "topics": len(decisions),
        "conflicts": sum(1 for d in decisions if d.superseded),
        "needs_review": sum(1 for d in decisions if d.needs_review),
    }
