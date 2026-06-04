"""IBC reference tables (abbreviated 2021 values).

Ported verbatim from plan-room-ahj/supabase/functions/_shared/rules.ts.
Values: a number is the tabular limit; "UL" = unlimited; "NP" = not permitted.

These are intentionally the abbreviated set that the demo engine needs, not
the full IBC. For a licensed production deployment these come from the
corpus, not a hardcoded table — but the math has to be deterministic, so the
limits live here.
"""
from __future__ import annotations

from typing import Dict, Union

# A cell is either an int (sf or stories), or one of the sentinels.
Cell = Union[int, str]  # "UL" | "NP" | int

# Table 506.2 — allowable area factor (sf per story), abbreviated.
IBC_T506_2: Dict[str, Dict[str, Cell]] = {
    "A-1": {"I-A": "UL", "I-B": "UL", "II-A": 15500, "II-B": 8500, "III-A": 14000, "III-B": 8500, "IV": 15000, "V-A": 11500, "V-B": 5500},
    "A-2": {"I-A": "UL", "I-B": "UL", "II-A": 15500, "II-B": 9500, "III-A": 14000, "III-B": 9500, "IV": 15000, "V-A": 11500, "V-B": 6000},
    "A-3": {"I-A": "UL", "I-B": "UL", "II-A": 15500, "II-B": 9500, "III-A": 14000, "III-B": 9500, "IV": 15000, "V-A": 11500, "V-B": 6000},
    "B":   {"I-A": "UL", "I-B": "UL", "II-A": 37500, "II-B": 23000, "III-A": 28500, "III-B": 19000, "IV": 36000, "V-A": 18000, "V-B": 9000},
    "E":   {"I-A": "UL", "I-B": "UL", "II-A": 26500, "II-B": 14500, "III-A": 23500, "III-B": 14500, "IV": 25500, "V-A": 18500, "V-B": 9500},
    "F-1": {"I-A": "UL", "I-B": "UL", "II-A": 25000, "II-B": 15500, "III-A": 19000, "III-B": 12000, "IV": 33500, "V-A": 14000, "V-B": 8500},
    "I-2": {"I-A": "UL", "I-B": 55000, "II-A": 26500, "II-B": "NP", "III-A": 26500, "III-B": "NP", "IV": 26500, "V-A": 18500, "V-B": "NP"},
    "M":   {"I-A": "UL", "I-B": "UL", "II-A": 21500, "II-B": 12500, "III-A": 18500, "III-B": 12500, "IV": 20500, "V-A": 14000, "V-B": 9000},
    "R-1": {"I-A": "UL", "I-B": "UL", "II-A": 24000, "II-B": 16000, "III-A": 24000, "III-B": 16000, "IV": 20500, "V-A": 12000, "V-B": 7000},
    "R-2": {"I-A": "UL", "I-B": "UL", "II-A": 24000, "II-B": 16000, "III-A": 24000, "III-B": 16000, "IV": 20500, "V-A": 12000, "V-B": 7000},
    "S-1": {"I-A": "UL", "I-B": 48000, "II-A": 26000, "II-B": 17500, "III-A": 26000, "III-B": 17500, "IV": 25500, "V-A": 14000, "V-B": 9000},
    "S-2": {"I-A": "UL", "I-B": 79000, "II-A": 39000, "II-B": 26000, "III-A": 39000, "III-B": 26000, "IV": 38500, "V-A": 21000, "V-B": 13500},
}

# Table 504.4 — allowable number of stories above grade, abbreviated.
IBC_T504_4: Dict[str, Dict[str, Cell]] = {
    "A-1": {"I-A": "UL", "I-B": 5, "II-A": 3, "II-B": 2, "III-A": 3, "III-B": 2, "IV": 3, "V-A": 2, "V-B": 1},
    "A-2": {"I-A": "UL", "I-B": 11, "II-A": 3, "II-B": 2, "III-A": 3, "III-B": 2, "IV": 3, "V-A": 2, "V-B": 1},
    "A-3": {"I-A": "UL", "I-B": 11, "II-A": 3, "II-B": 2, "III-A": 3, "III-B": 2, "IV": 3, "V-A": 2, "V-B": 1},
    "B":   {"I-A": "UL", "I-B": 11, "II-A": 5, "II-B": 3, "III-A": 5, "III-B": 3, "IV": 5, "V-A": 3, "V-B": 2},
    "E":   {"I-A": "UL", "I-B": 5, "II-A": 3, "II-B": 2, "III-A": 3, "III-B": 2, "IV": 3, "V-A": 1, "V-B": 1},
    "F-1": {"I-A": "UL", "I-B": 11, "II-A": 4, "II-B": 2, "III-A": 3, "III-B": 2, "IV": 4, "V-A": 2, "V-B": 1},
    "I-2": {"I-A": "UL", "I-B": 5, "II-A": 2, "II-B": "NP", "III-A": 1, "III-B": "NP", "IV": 1, "V-A": 1, "V-B": "NP"},
    "M":   {"I-A": "UL", "I-B": 11, "II-A": 4, "II-B": 2, "III-A": 4, "III-B": 2, "IV": 4, "V-A": 3, "V-B": 1},
    "R-1": {"I-A": "UL", "I-B": 11, "II-A": 4, "II-B": 4, "III-A": 4, "III-B": 4, "IV": 4, "V-A": 3, "V-B": 2},
    "R-2": {"I-A": "UL", "I-B": 11, "II-A": 4, "II-B": 4, "III-A": 4, "III-B": 4, "IV": 4, "V-A": 3, "V-B": 2},
    "S-1": {"I-A": "UL", "I-B": 11, "II-A": 4, "II-B": 2, "III-A": 3, "III-B": 2, "IV": 4, "V-A": 3, "V-B": 1},
    "S-2": {"I-A": "UL", "I-B": 11, "II-A": 5, "II-B": 3, "III-A": 4, "III-B": 3, "IV": 4, "V-A": 4, "V-B": 2},
}

# IBC 1006.3.2 — minimum number of exits by occupant load.
# (max_load, exits). The last bucket uses None for "no upper bound".
MIN_EXITS_BY_LOAD = [
    (500, 2),
    (1000, 3),
    (None, 4),
]

HIGH_RISE_FT = 75

# IPC Table 403.1 — abbreviated fixture ratios (occupants per fixture).
FIXTURE_RATIOS: Dict[str, Dict[str, int]] = {
    "A":   {"wc": 75, "lav": 200},
    "B":   {"wc": 25, "lav": 40},
    "E":   {"wc": 50, "lav": 50},
    "F":   {"wc": 100, "lav": 100},
    "I":   {"wc": 25, "lav": 25},
    "M":   {"wc": 500, "lav": 750},
    "R-1": {"wc": 10, "lav": 10},
    "R-2": {"wc": 10, "lav": 10},
    "S":   {"wc": 100, "lav": 100},
}
