"""Unit tests for geometry extraction (geometry_extractor).

Covers the pure, deterministic pieces — dimension parsing, the scale-note unit
chain (load-bearing: a wrong factor silently corrupts every measurement), layer
role classification, and the gray-wall clear-distance measurement. These need no
PDF and no API key; the full pipeline is exercised by scripts/geometry_validation.py
against real plan sets.
"""

import numpy as np
import pytest

from app.services.geometry_extractor import (
    parse_dimension_to_inches,
    parse_scale_note,
    classify_layer,
    measure_region_clear,
)


@pytest.mark.parametrize("token,expected", [
    ("10'-6\"", 126.0),       # feet-dash-inches, ASCII
    ("10′−6″", 126.0),  # same with Unicode prime / minus
    ("12'", 144.0),           # whole feet
    ("170.00'", 2040.0),      # decimal feet (survey)
    ("44\"", 44.0),           # inches only
    ("6 1/2\"", 6.5),         # fractional inches
    ("12'-6 1/2\"", 150.5),   # feet + fractional inches
    ("BEDROOM", None),        # not a dimension
    ("", None),
    (None, None),
])
def test_parse_dimension_to_inches(token, expected):
    assert parse_dimension_to_inches(token) == expected


def test_parse_dimension_divide_by_zero_is_safe():
    # A regex-valid but degenerate fraction must not raise.
    assert parse_dimension_to_inches("6 1/0\"") == 6.0
    assert parse_dimension_to_inches("10'-6 1/0\"") == 126.0


@pytest.mark.parametrize("note,ppf", [
    ("1/4\" = 1'", 18.0),     # the common residential plan scale
    ("1/8\"=1'", 9.0),
    ("3/8\" = 1'-0\"", 27.0),
    ("1\"=20'", 3.6),         # site scale
    ("1:48", 18.0),           # ratio form
])
def test_parse_scale_note_unit_chain(note, ppf):
    result = parse_scale_note(note)
    assert result is not None
    assert result[1] == pytest.approx(ppf)


@pytest.mark.parametrize("text", ["SCALE: NTS", "no scale here", ""])
def test_parse_scale_note_none(text):
    assert parse_scale_note(text) is None


@pytest.mark.parametrize("name,role", [
    ("S-Wall", "wall"),
    ("Wall- new", "wall"),
    ("A-ANNO-DIM-1_4", "dim"),
    ("JRN-DIMS", "dim"),           # DIM checked before ANNO
    ("Hatch", "hatch"),
    ("A-AREAS", "area"),
    ("A-ANNO-TEXT-3", "anno"),
    ("0", "other"),
    ("CAD_DEFAULT_LAYER", "other"),
    (None, "other"),
])
def test_classify_layer(name, role):
    assert classify_layer(name) == role


def _vwall(xc, y0=0.0, y1=400.0, t=6.0):
    """A vertical wall rect centered at x=xc (display space)."""
    return (xc - t / 2, y0, xc + t / 2, y1)


def test_measure_region_clear_clean_room():
    # Two vertical walls 180pt apart (face-to-face) at 18 pt/ft → 10.0 ft clear.
    walls = np.array([_vwall(103), _vwall(289)])   # right face 106, left face 286
    region = (106.0, 50.0, 286.0, 150.0)
    clear, conf, interior = measure_region_clear(walls, region, "V", ppf=18.0)
    assert clear == pytest.approx(10.0, abs=0.05)
    assert conf == 0.9 and interior == 0


def test_measure_region_clear_interior_wall_lowers_confidence():
    # A partition between the brackets → ambiguous → advisory confidence.
    walls = np.array([_vwall(103), _vwall(200), _vwall(289)])
    region = (106.0, 50.0, 286.0, 150.0)
    clear, conf, interior = measure_region_clear(walls, region, "V", ppf=18.0)
    assert clear == pytest.approx(10.0, abs=0.05)
    assert conf == 0.4 and interior == 1


def test_measure_region_clear_degenerate_returns_none():
    assert measure_region_clear(np.empty((0, 4)), (0, 0, 10, 10), "V", 18.0) is None
    walls = np.array([_vwall(103), _vwall(289)])
    assert measure_region_clear(walls, (106, 50, 286, 150), "bogus", 18.0) is None
    assert measure_region_clear(walls, (106, 50, 286, 150), "V", 0.0) is None
