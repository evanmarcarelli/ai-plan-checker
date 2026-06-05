"""Pilot configuration — single source of truth for the 90% target knobs.

Ported from plan-room-ahj/supabase/functions/_shared/pilot_config.ts. Every
threshold the pipeline uses to enforce the 90% / broad-scope pilot brief
lives here. Touch this file when you want to change a gate; do NOT scatter
magic numbers across workflow.py / critic.py / archetype.py. The brief
itself is at docs/PILOT_BRIEF.md.

Rule of thumb: if a number in this file would change for the 99% roadmap,
it belongs here.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


# =====================================================================
# Project archetype enum (mirrors archetype.py — kept here to avoid an
# import cycle between archetype.py and pilot.py).
# =====================================================================
# In-pilot archetypes (LA + Ventura)
ARCHETYPE_LA_SFR_TYP_VB_MINISTERIAL = "la_sfr_typ_vb_ministerial"
ARCHETYPE_LA_TI_COMMERCIAL = "la_ti_commercial"
ARCHETYPE_VENTURA_SFR_TYP_VB_MINISTERIAL = "ventura_sfr_typ_vb_ministerial"
ARCHETYPE_VENTURA_TI_COMMERCIAL = "ventura_ti_commercial"

# Out-of-pilot archetypes (each maps to a specific human-readable reason)
ARCHETYPE_LA_HILLSIDE_SFR = "la_hillside_sfr"
ARCHETYPE_LA_HPOZ_PROPERTY = "la_hpoz_property"
ARCHETYPE_LA_COASTAL_ZONE = "la_coastal_zone"
ARCHETYPE_VENTURA_VHFHSZ_SFR = "ventura_vhfhsz_sfr"
ARCHETYPE_VENTURA_AG_BUILDING = "ventura_ag_building"
ARCHETYPE_HIGH_RISE_OR_MID_RISE = "high_rise_or_mid_rise"
ARCHETYPE_MULTIFAMILY_NEW_CONSTRUCTION = "multifamily_new_construction"
ARCHETYPE_MIXED_USE_NEW_CONSTRUCTION = "mixed_use_new_construction"
ARCHETYPE_UNCLASSIFIED = "unclassified"


# =====================================================================
# Accuracy targets (read by the eval harness + check-pilot-targets CLI)
# =====================================================================
@dataclass(frozen=True)
class PilotTargets:
    """Accuracy targets the pilot brief commits to."""
    # When the system says "fail", ground truth agrees >= this rate.
    per_finding_precision_min: float = 0.90
    # The system catches >= this share of real issues.
    per_finding_recall_min: float = 0.85
    # When the archetype gate says "reject", it's right >= this rate.
    out_of_scope_rejection_precision_min: float = 0.95
    # Per-archetype F1 may drop at most this much between labeled runs.
    per_archetype_f1_regression_tolerance: float = 0.02
    # Minimum number of ground-truth observations for an archetype to be
    # evaluated against the targets (below this, results are noise).
    min_observations_per_archetype: int = 10


PILOT_TARGETS = PilotTargets()


# =====================================================================
# Pipeline gates (read by workflow.py and critic.py)
# =====================================================================
@dataclass(frozen=True)
class PipelineGates:
    """Numeric gates the pipeline applies at each stage."""
    # A "fail" finding needs a citation at least this confident to ship.
    # Below this, the finding is auto-downgraded to "warn" by the citation
    # gate. 0.5 keeps recall up; raise toward 0.7 to trade recall for
    # precision. Brief Hard NO: > 0.80.
    citation_min_confidence: float = 0.5

    # Confidence below this auto-routes the finding to the human-review
    # queue instead of shipping it as "fail".
    finding_ship_min_confidence: float = 0.75

    # Adversarial critic verdict confidence at-or-above which a dissent
    # triggers a hard downgrade (fail → needs_review). Below this, the
    # finding stays as fail but gets a "models disagree" tag.
    critic_hard_downgrade_confidence: float = 0.7

    # Max number of findings the critic loop runs per submittal. Bounds
    # cost at ~$0.25 per submittal. Brief Hard NO: increasing to an
    # N-of-5 ensemble.
    critic_max_findings_per_run: int = 5

    # Max number of citation-research enrichments per submittal.
    # Each one is ~$0.05-0.20 in search + LLM.
    research_max_citations_per_run: int = 5


PIPELINE_GATES = PipelineGates()


# =====================================================================
# Pilot scope — the archetype allowlist
#
# Mirrors the brief's "In-pilot scope" table. Per-agency overrides can
# be layered on top by passing pilot_archetypes to classify_archetype.
# =====================================================================
PILOT_ARCHETYPES_DEFAULT: tuple[str, ...] = (
    ARCHETYPE_LA_SFR_TYP_VB_MINISTERIAL,
    ARCHETYPE_LA_TI_COMMERCIAL,
    ARCHETYPE_VENTURA_SFR_TYP_VB_MINISTERIAL,
    ARCHETYPE_VENTURA_TI_COMMERCIAL,
)


# Archetypes that get triaged but are flagged as "edge — needs extra
# reviewer attention" in the dashboard. Empty until the classifier
# emits these labels.
PILOT_EDGE_ARCHETYPES: tuple[str, ...] = ()


# =====================================================================
# Helpers
# =====================================================================

def using_default_pilot_scope(agency_pilot_archetypes: Optional[list[str]]) -> bool:
    """True iff the agency hasn't overridden the default pilot scope."""
    return not agency_pilot_archetypes or len(agency_pilot_archetypes) == 0


def format_pilot_targets() -> str:
    """Render the pilot targets as a one-line banner for logs / dashboards."""
    t = PILOT_TARGETS
    return (
        f"90% pilot target: precision >= {int(t.per_finding_precision_min * 100)}%, "
        f"recall >= {int(t.per_finding_recall_min * 100)}%, "
        f"gate precision >= {int(t.out_of_scope_rejection_precision_min * 100)}%"
    )
