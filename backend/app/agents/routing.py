"""Department routing pre-screen — the Phase 2 cost lever.

All 10 LLM department reviewers run on every plan today. For an archetype
whose irrelevance to a department is PROVABLE, this picks only the applicable
departments so the others are never invoked (a direct token + latency win).

Cardinal rule: FAIL OPEN. When the archetype is unknown, out of pilot scope,
or not in the skip map, EVERY department runs. A department is skipped only
when its irrelevance to that archetype is provable (see
config.pilot.ARCHETYPE_SKIP_DEPARTMENTS). Skipping the WRONG department loses
a real finding; running an extra one only costs tokens — so the bias is always
toward running.

Pure function: no LLM, no network, no I/O. Unit-tested in
tests/test_department_selection.py.
"""
from __future__ import annotations

from typing import Iterable, Optional, Set

from app.agents.archetype import ArchetypeResult
from app.config.pilot import ARCHETYPE_SKIP_DEPARTMENTS


def select_departments(
    all_categories: Iterable[str],
    archetype: Optional[ArchetypeResult],
) -> Set[str]:
    """Return the subset of department categories to run for this submittal.

    Args:
        all_categories: every department's `.category` (the full panel).
        archetype: the intake archetype verdict, or None if classification
            did not run.

    Returns:
        The set of categories to run. Always a subset of `all_categories`.
        Fails OPEN: returns the full set unless the archetype is in pilot
        scope AND appears in ARCHETYPE_SKIP_DEPARTMENTS, in which case only
        that archetype's provably-irrelevant categories are removed.
    """
    full = set(all_categories)

    # Fail open on any missing / ambiguous signal.
    if archetype is None:
        return full
    if not archetype.in_pilot_scope:
        return full

    skip = ARCHETYPE_SKIP_DEPARTMENTS.get(archetype.archetype)
    if not skip:
        return full

    # Only ever remove categories the panel actually has; never invent or keep
    # categories outside `all_categories`.
    return full - set(skip)
