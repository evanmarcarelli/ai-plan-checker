"""Geometry-extraction accuracy harness (read-only; not part of the request pipeline).

Run against real plan-set PDFs to measure how well geometry extraction is doing,
WITHOUT needing external ground truth. The backbone is the self-consistency check:
every dimension token the architect printed is its own test case — under the
calibrated scale, a token's stated length should match a real drawn segment near
it. Tight agreement = scale + drawing + unit-chain all correct; outliers flag a
bad scale or a self-contradictory drawing.

Usage:
    python -m scripts.geometry_validation "C:/path/to/plan.pdf" [more.pdf ...]
    python -m scripts.geometry_validation            # scans ./uploads for *.pdf

Reports per file: routing, scale coverage, dominant scale, and a self-consistency
score per scaled page. Exit code is non-zero if a hard sanity assertion fails
(e.g. the unit-chain math is wrong), so this can gate CI.
"""

import sys
import glob
from pathlib import Path

# Allow running as a loose script (python scripts/geometry_validation.py) too.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import fitz  # noqa: E402
from app.services.geometry_extractor import (  # noqa: E402
    geometry_extractor, parse_scale_note, harvest_dimension_tokens,
    _explode_segments, corroborate_scale,
)

try:
    sys.stdout.reconfigure(encoding="utf-8")  # CAD dimensions use ′ ″ − glyphs
except Exception:
    pass


def _assert_unit_chain() -> None:
    """The non-negotiable invariant: scale-note math must be exact. A wrong unit
    chain yields plausible-but-wrong measurements — worse than none."""
    cases = [('1/4" = 1\'', 18.0), ("1/8\"=1'", 9.0), ("1\"=20'", 3.6), ("1:48", 18.0)]
    for note, expect in cases:
        r = parse_scale_note(note)
        assert r is not None, f"scale note not parsed: {note!r}"
        assert abs(r[1] - expect) < 1e-6, f"unit chain wrong for {note!r}: {r[1]} != {expect}"
    print("[ok] unit-chain assertions passed")


def validate_file(path: str) -> dict:
    print(f"\n{'='*70}\n{path}\n{'='*70}")
    doc = fitz.open(path)
    gd = geometry_extractor.extract(path)
    if gd is None:
        print("  extract() returned None")
        return {"file": path, "ok": False}

    ds = gd.dominant_scale
    print(f"pages={gd.stats['pages']} layers={gd.stats['layer_count']} "
          f"routing={gd.stats['routing']} scaled={gd.stats['scaled_pages']}")
    print(f"dominant_scale={ds.scale_text if ds else None} "
          f"({ds.points_per_foot if ds else None} pt/ft, conf {ds.confidence if ds else None})")

    # Self-consistency per scaled page: corroboration rate under the page scale.
    print(f"\n{'pg':>3} | {'ppf':>5} | {'tokens':>6} | {'corrob':>6} | rate  | verdict")
    rates = []
    for p in gd.pages:
        s = p.scale
        if not (s and s.points_per_foot):
            continue
        page = doc[p.page - 1]
        tokens = harvest_dimension_tokens(page)
        if not tokens:
            continue
        segs = _explode_segments(page.get_drawings())
        corr, checked = corroborate_scale(tokens, segs, s.points_per_foot)
        rate = (corr / checked) if checked else 0.0
        rates.append(rate)
        verdict = "strong" if rate >= 0.4 else ("ok" if rate >= 0.2 else "weak")
        print(f"{p.page:>3} | {s.points_per_foot:>5.1f} | {checked:>6} | {corr:>6} | "
              f"{rate:>4.0%} | {verdict}")
    doc.close()

    avg = (sum(rates) / len(rates)) if rates else 0.0
    print(f"\nmean self-consistency rate: {avg:.0%} over {len(rates)} scaled pages")
    return {"file": path, "ok": True, "dominant_ppf": ds.points_per_foot if ds else None,
            "scaled_pages": gd.stats["scaled_pages"], "mean_consistency": avg}


def main(argv: list) -> int:
    _assert_unit_chain()
    paths = argv[1:] or sorted(glob.glob("uploads/*.pdf"))
    if not paths:
        print("no PDFs given and none in ./uploads — pass a path argument")
        return 1
    results = [validate_file(p) for p in paths]
    print(f"\n{'='*70}\nSUMMARY")
    for r in results:
        if r.get("ok"):
            print(f"  {Path(r['file']).name}: scale={r['dominant_ppf']} pt/ft, "
                  f"{r['scaled_pages']} scaled pages, consistency {r['mean_consistency']:.0%}")
        else:
            print(f"  {Path(r['file']).name}: FAILED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
