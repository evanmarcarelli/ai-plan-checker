"""Pydantic models for the adoption map.

Validates `adoption_map.yaml` on load (same validate-on-load discipline as
corpus_loader). A bad record fails loudly at startup rather than silently
producing a wrong code stack downstream.
"""
from __future__ import annotations

from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class DisciplineAdoption(BaseModel):
    """One discipline's adopted code (e.g. building -> 2025 CBC / 2024 IBC)."""
    code: str                              # "CBC", "CRC", "CEC", ...
    edition: str                           # "2025"
    part: Optional[str] = None             # "T24 Pt 2"
    base_model: Optional[str] = None       # "2024 IBC"


class GeoMatch(BaseModel):
    state_code: Optional[str] = None
    county: Optional[str] = None
    city: Optional[str] = None
    place_fips: Optional[str] = None


class AmendmentSource(BaseModel):
    layer: str                             # interpretation | corrections | local_amend | state_model | base_model
    kind: str
    url: Optional[str] = None
    slug: Optional[str] = None
    # public_pdf | public_index | cloudflare_blocked | buy_license
    access: str


class AmendmentRelationship(str, Enum):
    """How a local amendment relates to the base code it modifies.

    This is the precedence signal the resolver needs to answer "which law
    governs": standards default to the more-restrictive provision, zoning is
    local-unless-preempted, overlays stack on top.
    """
    MORE_RESTRICTIVE = "more_restrictive"      # standards: stricter of base vs local governs (H&S 17958.5)
    REPLACES = "replaces"                       # local text supersedes base for this jurisdiction
    ADDS = "adds"                               # local adds requirements on top of base (union)
    PREEMPTED_BY_STATE = "preempted_by_state"   # local overridden by a state statute (zoning carve-outs)
    OVERLAY = "overlay"                          # additive overlay layer; stacks, never replaces


class AmendmentRelation(BaseModel):
    """Structured sibling of the prose `local_amendments` label.

    `label` carries the same human string the prose field has (kept for
    back-compat); the rest is machine-readable precedence data.
    """
    label: str
    relationship: AmendmentRelationship = AmendmentRelationship.MORE_RESTRICTIVE
    preempted_by: List[str] = Field(default_factory=list)   # carve-out ids (e.g. ["adu","sb9"])
    base_path: Optional[str] = None                          # v2 provision pointer (ltree); unused by v1 logic
    ordinance_cite: Optional[str] = None


class PreemptionCarveout(BaseModel):
    """A state statute that preempts conflicting local (usually zoning) law."""
    id: str                                # "adu" | "sb9" | "density_bonus" | "coastal_act"
    statute: str                           # "Gov. Code 66310 et seq."
    topic: str = "zoning"                  # the topic this carve-out governs
    summary: str = ""
    applies_when: Optional[str] = None     # human note on the trigger condition


class PrecedenceConfig(BaseModel):
    """Top-level `precedence:` block in adoption_map.yaml."""
    carveouts: List[PreemptionCarveout] = Field(default_factory=list)


class AdoptionRecord(BaseModel):
    id: str
    level: str                             # state | county | city
    names: List[str] = Field(default_factory=list)
    geo: GeoMatch = Field(default_factory=GeoMatch)
    authority: Optional[str] = None
    inherits: Optional[str] = None         # id of parent record
    edition_cycle: Optional[str] = None
    prior_edition: Optional[str] = None
    prior_effective_until: Optional[str] = None
    adopts: Dict[str, DisciplineAdoption] = Field(default_factory=dict)
    local_amendments: Dict[str, str] = Field(default_factory=dict)
    # Structured precedence siblings (back-compatible; default empty). The
    # resolver folds these down the inheritance chain alongside local_amendments.
    amendment_relations: Dict[str, AmendmentRelation] = Field(default_factory=dict)
    adopts_by_reference: List[str] = Field(default_factory=list)   # other record ids (Malibu -> LA County)
    overlays: List[str] = Field(default_factory=list)
    corpus_layer_keys: List[str] = Field(default_factory=list)
    sources: List[AmendmentSource] = Field(default_factory=list)

    def matches(self, state: Optional[str], county: Optional[str], city: Optional[str]) -> int:
        """Return a specificity score if this record matches the given
        jurisdiction, else -1. Higher = more specific (city beats county
        beats state). City and county must match by name OR geo.
        """
        if state and self.geo.state_code and state.upper() != self.geo.state_code.upper():
            return -1

        if self.level == "city":
            if not city:
                return -1
            if not _name_match(city, self.names, self.geo.city):
                return -1
            return 3
        if self.level == "county":
            if not county:
                return -1
            if not _name_match(county, self.names, self.geo.county):
                return -1
            return 2
        if self.level == "state":
            if not state:
                return -1
            return 1
        return -1


def _name_match(value: str, names: List[str], geo_name: Optional[str]) -> bool:
    v = value.strip().lower()
    candidates = [n.lower() for n in names]
    if geo_name:
        candidates.append(geo_name.lower())
    # Match if the candidate name appears in the value or vice-versa
    # ("Los Angeles" vs "City of Los Angeles" vs "los angeles, ca").
    for c in candidates:
        if c and (c in v or v in c):
            return True
    return False
