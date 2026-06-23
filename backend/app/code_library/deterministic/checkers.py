"""Deterministic checker primitives.

Pure functions over typed scalars. Ported from
plan-room-ahj/supabase/functions/_shared/checkers.ts. Everything here is
unit-testable without the LLM, the corpus, or the network.

Conventions (same as the TS original):
  - Inputs are the minimum required scalars so each function is independently
    testable.
  - Every checker returns the same CheckResult shape.
  - "info"  = cannot evaluate (missing input).
  - "warn"  = technically a violation but the input is ambiguous/incomplete.
  - "fail"  = a concrete, certain violation.
  - "pass"  = checked and compliant.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional

from app.code_library.deterministic import table_store

CheckStatus = str  # "pass" | "fail" | "warn" | "info"


@dataclass
class CheckResult:
    status: CheckStatus
    summary: str
    evidence: List[str] = field(default_factory=list)


def _info(summary: str) -> CheckResult:
    return CheckResult("info", summary)


def _pass(summary: str, evidence: Optional[List[str]] = None) -> CheckResult:
    return CheckResult("pass", summary, evidence or [])


def _fail(summary: str, evidence: Optional[List[str]] = None) -> CheckResult:
    return CheckResult("fail", summary, evidence or [])


def _warn(summary: str, evidence: Optional[List[str]] = None) -> CheckResult:
    return CheckResult("warn", summary, evidence or [])


def _fmt(n: float) -> str:
    """Thousands-separated integer formatting to match the TS toLocaleString()."""
    return f"{int(n):,}"


def _fmt_dim(n: float) -> str:
    """Like _fmt but preserves a fractional part (e.g. 7.75" CRC riser max),
    which the integer _fmt would silently truncate to '7'."""
    return f"{int(n):,}" if float(n).is_integer() else f"{n:,g}"


# =====================================================================
# Allowable area (IBC Table 506.2)
# =====================================================================
def check_allowable_area(
    occupancy_primary: Optional[str],
    construction_type: Optional[str],
    area_sf: Optional[float],
    sprinklered: Optional[bool] = None,
) -> CheckResult:
    if not occupancy_primary or not construction_type:
        return _info("Cannot evaluate — occupancy or construction type missing.")
    if area_sf is None:
        return _warn("Building area not declared.")
    row = table_store.t506_2().get(occupancy_primary)
    if row is None:
        return _info(f"No Table 506.2 row for {occupancy_primary}.")
    allowable = row.get(construction_type)
    if allowable is None:
        return _info(f"Type {construction_type} not in row for {occupancy_primary}.")
    if allowable == "UL":
        return _pass("Unlimited area for this occupancy / type.")
    if allowable == "NP":
        return _fail(f"{occupancy_primary} NOT PERMITTED in Type {construction_type}.")
    if area_sf > allowable:
        # The stored value is the NON-SPRINKLERED tabular factor. A CONFIRMED
        # sprinklered building may legally be 3-4x larger (506.2 S1/SM rows)
        # — flag for the increase math instead of hard-failing. Unknown
        # sprinkler status fails against the NS row, exactly as an examiner
        # writes the correction: the applicant must demonstrate the increase.
        if sprinklered is True:
            return _warn(
                f"Area {_fmt(area_sf)} sf exceeds the {_fmt(allowable)} sf NS tabular value "
                f"for Group {occupancy_primary} / Type {construction_type}. Sprinklered — "
                f"verify the increased allowable area under IBC 506.2 (S1/SM rows) and 506.3."
            )
        return _fail(
            f"Area {_fmt(area_sf)} sf exceeds tabular {_fmt(allowable)} sf for "
            f"Group {occupancy_primary} / Type {construction_type}. "
            f"Demonstrate sprinkler (506.2) and/or frontage (506.3) increases, "
            f"or reduce the area.",
            [f"{_fmt(area_sf)} sf actual", f"{_fmt(allowable)} sf NS tabular"],
        )
    return _pass(f"Area {_fmt(area_sf)} sf within {_fmt(allowable)} sf tabular limit.")


# =====================================================================
# Allowable height in feet (IBC Table 504.3)
# =====================================================================
def check_allowable_height(
    construction_type: Optional[str],
    height_ft: Optional[float],
    sprinklered: Optional[bool],
) -> CheckResult:
    """Height in FEET vs Table 504.3 (NS row; sprinklering adds 20 ft per
    IBC 504.2). Closes the gap where a 60-ft Type V-B building sailed past
    the only height check in the engine — the 75-ft high-rise threshold —
    despite a 40 ft NS / 60 ft S actual limit."""
    if not construction_type:
        return _info("Cannot evaluate — construction type missing.")
    if height_ft is None:
        return _warn("Building height not declared.")
    lim = table_store.t504_3_ns_ft().get(construction_type)
    if lim is None:
        return _info(f"No Table 504.3 value for Type {construction_type}.")
    if lim == "UL":
        return _pass("Unlimited height for this construction type.")
    # Consistent posture with the area/stories checks: compare against the
    # NS row unless sprinklering is CONFIRMED (then +20 ft per IBC 504.2);
    # the failure message points at the sprinkler path the applicant can take.
    eff = lim + 20 if sprinklered is True else lim
    if height_ft > eff:
        suffix = " incl. sprinkler increase" if sprinklered is True else " (NS row)"
        hint = (
            f" If the building is fully sprinklered, the limit is {_fmt(lim + 20)} ft "
            f"— demonstrate it on the plans." if sprinklered is not True else ""
        )
        return _fail(
            f"Height {_fmt(height_ft)} ft exceeds the {_fmt(eff)} ft limit "
            f"(Table 504.3{suffix}) for Type {construction_type}.{hint}",
            [f"{_fmt(height_ft)} ft actual", f"{_fmt(eff)} ft allowable"],
        )
    return _pass(f"Height {_fmt(height_ft)} ft within the {_fmt(eff)} ft limit.")


# =====================================================================
# Generic minimum-dimension scalar (CRC R-3 pack)
# =====================================================================
def check_min_dimension(
    value: Optional[float],
    minimum: float,
    unit: str,
    label: str,
    code_ref: str,
) -> CheckResult:
    """One extracted dimension vs a code minimum. None → warn (not found),
    never a false fail — absence of a regex match is not a violation."""
    if value is None:
        return _warn(f"{label} not found on plans — verify {code_ref} minimum of {_fmt(minimum)}{unit}.")
    if value < minimum:
        return _fail(
            f"{label} {_fmt(value)}{unit} is below the {_fmt(minimum)}{unit} minimum ({code_ref}).",
            [f"{_fmt(value)}{unit} shown", f"{_fmt(minimum)}{unit} required"],
        )
    return _pass(f"{label} {_fmt(value)}{unit} meets the {_fmt(minimum)}{unit} minimum.")


def check_max_dimension(
    value: Optional[float],
    maximum: float,
    unit: str,
    label: str,
    code_ref: str,
) -> CheckResult:
    """One extracted dimension vs a code maximum (mirror of check_min_dimension
    for upper-bound limits like stair riser height). None → warn (not found),
    never a false fail — absence of a regex match is not a violation."""
    if value is None:
        return _warn(f"{label} not found on plans — verify {code_ref} maximum of {_fmt_dim(maximum)}{unit}.")
    if value > maximum:
        return _fail(
            f"{label} {_fmt_dim(value)}{unit} exceeds the {_fmt_dim(maximum)}{unit} maximum ({code_ref}).",
            [f"{_fmt_dim(value)}{unit} shown", f"{_fmt_dim(maximum)}{unit} allowed"],
        )
    return _pass(f"{label} {_fmt_dim(value)}{unit} within the {_fmt_dim(maximum)}{unit} maximum.")


# =====================================================================
# Allowable stories (IBC Table 504.4)
# =====================================================================
def check_allowable_stories(
    occupancy_primary: Optional[str],
    construction_type: Optional[str],
    stories_above: Optional[int],
    sprinklered: Optional[bool],
) -> CheckResult:
    if not occupancy_primary or not construction_type:
        return _info("Cannot evaluate — occupancy or construction type missing.")
    if stories_above is None:
        return _warn("Number of stories not declared.")
    row = table_store.t504_4().get(occupancy_primary)
    if row is None:
        return _info(f"No Table 504.4 row for {occupancy_primary}.")
    lim = row.get(construction_type)
    if lim == "UL":
        return _pass("Unlimited stories for this occupancy / type.")
    if lim == "NP":
        return _fail("Occupancy NOT PERMITTED in this construction type.")
    if lim is None:
        return _info(f"Type {construction_type} not in row for {occupancy_primary}.")
    # The stored table is the NON-SPRINKLERED (NS) row of Table 504.4.
    # Sprinklering (NFPA 13 / IBC 504.2) ADDS a story over the NS base —
    # the prior model subtracted one for non-sprinklered buildings from
    # values that were already the NS row, failing legal 2-story NS
    # buildings and legal 3-story sprinklered ones.
    eff = lim + 1 if sprinklered is True else lim
    if stories_above > eff:
        suffix = " + sprinkler increase" if sprinklered is True else " (NS row)"
        return _fail(f"{stories_above} stories exceeds {eff}-story limit (Table 504.4{suffix}).")
    return _pass(f"{stories_above} stories within {eff}-story limit.")


# =====================================================================
# Minimum exits required (IBC 1006.3.2)
# =====================================================================
def required_min_exits(occupant_load: int) -> int:
    buckets = table_store.min_exits_by_load()
    for max_load, exits in buckets:
        if max_load is None or occupant_load <= max_load:
            return exits
    return buckets[-1][1]


def check_min_exits(occupant_load: Optional[int], declared_exits: Optional[int]) -> CheckResult:
    if occupant_load is None:
        return _info("Occupant load not declared.")
    required = required_min_exits(occupant_load)
    if declared_exits is None:
        # "We couldn't count the exits" is not "zero exits" — treating an
        # unextracted count as 0 false-failed every plan whose exits weren't
        # machine-readable the moment occupant load became available.
        return _warn(
            f"OL {occupant_load} requires {required} exit(s); exit count could "
            f"not be read from the plans — verify."
        )
    if declared_exits >= required:
        return _pass(f"{declared_exits} exit(s); {required} required for OL {occupant_load}.")
    return _fail(f"OL {occupant_load} requires {required} exits; only {declared_exits} labeled.")


# =====================================================================
# Exit capacity (IBC 1005.3) — door 0.2 in/occ, stair 0.3 in/occ
# =====================================================================
def required_door_width_in(occupant_load: int) -> float:
    return occupant_load * 0.2


def required_stair_width_in(occupant_load: int) -> float:
    return occupant_load * 0.3


def check_exit_capacity(
    occupant_load: Optional[int],
    declared_door_width_in: float,
    declared_stair_width_in: float,
) -> CheckResult:
    if occupant_load is None:
        return _info("Occupant load not declared.")
    req_door = required_door_width_in(occupant_load)
    req_stair = required_stair_width_in(occupant_load)
    if declared_door_width_in == 0 and declared_stair_width_in == 0:
        return _warn(
            f"Need >={req_door:.1f}\" total door width for OL {occupant_load}; "
            f"no labeled exit doors found."
        )
    issues: List[str] = []
    if declared_door_width_in and declared_door_width_in < req_door:
        issues.append(f"door capacity {declared_door_width_in}\" < {req_door:.1f}\" required")
    if declared_stair_width_in and declared_stair_width_in < req_stair:
        issues.append(f"stair capacity {declared_stair_width_in}\" < {req_stair:.1f}\" required")
    if issues:
        return _fail(f"Exit capacity insufficient for OL {occupant_load}: {'; '.join(issues)}.")
    return _pass(f"Exit capacity OK for OL {occupant_load}.")


# =====================================================================
# High-rise threshold (IBC 403)
# =====================================================================
def is_high_rise(height_ft: Optional[float]) -> bool:
    return height_ft is not None and height_ft > table_store.high_rise_ft()


def check_high_rise(height_ft: Optional[float], sprinklered: Optional[bool]) -> CheckResult:
    if height_ft is None:
        return _info("Building height not declared.")
    threshold = table_store.high_rise_ft()
    if not is_high_rise(height_ft):
        return _pass(f"{_fmt(height_ft)} ft is below the {threshold} ft high-rise threshold.")
    # High-rise: IBC 403 provisions apply. We can't verify smoke control /
    # voice alarm / standby power from scope alone, so this is a warn that
    # the reviewer must confirm those systems are on the plans.
    return _warn(
        f"{_fmt(height_ft)} ft exceeds {threshold} ft — high-rise (IBC 403): "
        f"verify smoke control, voice alarm, and standby power are provided."
    )


# =====================================================================
# Plumbing fixtures (IPC Table 403.1) — abbreviated ratios
# =====================================================================
def required_fixture_count(occupancy_primary: str, occupant_load: int):
    ratios = table_store.fixture_ratios()
    key = occupancy_primary if occupancy_primary in ratios else occupancy_primary[:1]
    r = ratios.get(key)
    if not r:
        return None
    return {
        "wc": math.ceil(occupant_load / r["wc"]),
        "lav": math.ceil(occupant_load / r["lav"]),
    }


def check_fixtures(
    occupancy_primary: Optional[str],
    occupant_load: Optional[int],
    actual_wc: Optional[int],
    actual_lav: Optional[int],
) -> CheckResult:
    if occupant_load is None or not occupancy_primary:
        return _info("Cannot calculate fixtures without occupant load + occupancy.")
    req = required_fixture_count(occupancy_primary, occupant_load)
    if not req:
        return _info(f"No fixture ratios for {occupancy_primary}.")
    if actual_wc is None and actual_lav is None:
        return _warn(
            f"Need >={req['wc']} WC / {req['lav']} lav for OL {occupant_load}; "
            f"no fixture schedule found."
        )
    issues: List[str] = []
    if actual_wc is not None and actual_wc < req["wc"]:
        issues.append(f"WC {actual_wc} < {req['wc']} required")
    if actual_lav is not None and actual_lav < req["lav"]:
        issues.append(f"Lav {actual_lav} < {req['lav']} required")
    if issues:
        return _fail(f"Fixtures short: {'; '.join(issues)}.")
    return _pass(
        f"Fixtures OK: {actual_wc if actual_wc is not None else '?'} WC / "
        f"{actual_lav if actual_lav is not None else '?'} lav meet {req['wc']} / {req['lav']}."
    )
