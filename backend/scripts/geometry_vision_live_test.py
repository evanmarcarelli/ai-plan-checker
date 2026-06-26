"""Live Phase-D vision test (REQUIRES an Anthropic API key).

This is the one validation the audit could not do offline: does Claude vision
actually locate corridors / egress / doors on real floor plans well enough that
the gray-wall geometry measures the right gap?

It calls the LIVE vision path (geometry_vision_measurer) on real pages, measures
each located feature against the geometry, and writes an annotated image per page
so you can eyeball — box-by-box — whether vision pointed at the right thing and the
measured number is plausible. Green box = high-confidence measurement, orange =
low-confidence (ambiguous region), red = vision located it but geometry couldn't
measure (no clean wall bracket).

Usage:
    # provide a key first (it's in Render's env in prod; locally:)
    #   ! export ANTHROPIC_API_KEY=sk-ant-...
    python -m scripts.geometry_vision_live_test "C:/path/to/plan.pdf"
    python -m scripts.geometry_vision_live_test plan.pdf --pages 14,15 --out ./vis_out

Bypasses the GEOMETRY_*_ENABLED flags on purpose (the script's whole job is to
exercise the path); it only needs the API key. No files in the repo are modified.
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import fitz  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

from app.config import settings  # noqa: E402
from app.services.geometry_extractor import (  # noqa: E402
    geometry_extractor, gray_wall_rects_display, measure_region_clear,
)
from app.services.geometry_vision import geometry_vision_measurer as M  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

VIEW_DPI = 130  # resolution of the saved annotated image (independent of the
                # 1536px image actually sent to the model)


async def _run(pdf_path: str, pages_arg: str, out_dir: Path) -> int:
    if not settings.anthropic_api_key:
        print("ERROR: ANTHROPIC_API_KEY is not set — this script needs it to call "
              "Claude vision.\n  Locally:  ! export ANTHROPIC_API_KEY=sk-ant-...\n"
              "  (In production the key is in Render's environment.)")
        return 2

    out_dir.mkdir(parents=True, exist_ok=True)
    doc = fitz.open(pdf_path)

    # Per-page + dominant scale (the measurement needs points-per-foot).
    geometry = geometry_extractor.extract(pdf_path)
    if geometry is None:
        print("ERROR: geometry extraction returned nothing.")
        return 1
    dom = geometry.dominant_scale.points_per_foot if geometry.dominant_scale else None

    if pages_arg:
        pages = [int(p) for p in pages_arg.split(",") if p.strip()]
    else:
        pages = M._candidate_pages(geometry)
    print(f"Testing live vision on pages: {pages}  (dominant scale "
          f"{geometry.dominant_scale.scale_text if geometry.dominant_scale else None})\n")

    total_feats = total_measured = 0
    for pno in pages:
        page = doc[pno - 1]
        pg_geo = next((p for p in geometry.pages if p.page == pno), None)
        ppf = (pg_geo.scale.points_per_foot if (pg_geo and pg_geo.scale and
               pg_geo.scale.points_per_foot) else dom)
        if not ppf:
            print(f"PAGE {pno}: no usable scale — skipping.")
            continue

        b64 = M._render_jpeg_b64(page, pno)
        result = await M._call_vision(b64, pno)          # LIVE vision call
        if not result:
            print(f"PAGE {pno}: vision returned nothing (error: {M.last_error}).")
            continue
        if not result.get("is_floor_plan"):
            print(f"PAGE {pno}: vision says NOT a floor plan (correctly skips elevations/sections).")
            continue

        walls = gray_wall_rects_display(page)
        disp_w, disp_h = page.rect.width, page.rect.height
        feats = result.get("features", []) or []
        print(f"PAGE {pno}: vision located {len(feats)} feature(s) @ {ppf} pt/ft")

        # annotated render
        pix = page.get_pixmap(dpi=VIEW_DPI)
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        draw = ImageDraw.Draw(img)

        for f in feats:
            total_feats += 1
            bbox = f.get("bbox")
            axis = {"width": "V", "height": "H"}.get(f.get("measure_axis"))
            label = f.get("label") or f.get("type") or "?"
            if not bbox or len(bbox) != 4 or axis is None:
                print(f"    - {label}: malformed feature, skipped")
                continue
            try:
                nx0, ny0, nx1, ny1 = (float(v) for v in bbox)
            except (TypeError, ValueError):
                print(f"    - {label}: non-numeric bbox, skipped")
                continue

            region = (nx0 * disp_w, ny0 * disp_h, nx1 * disp_w, ny1 * disp_h)
            m = measure_region_clear(walls, region, axis, ppf)
            box_px = [nx0 * pix.width, ny0 * pix.height, nx1 * pix.width, ny1 * pix.height]
            if m is None:
                color = (220, 0, 0)
                tag = f"{label}: NO MEASURE"
                print(f"    - {label} [{f.get('type')}]: located, geometry could not measure")
            else:
                clear_ft, conf, interior = m
                total_measured += 1
                color = (0, 160, 0) if conf >= 0.7 else (230, 140, 0)
                tag = f"{label}: {clear_ft}ft ({conf})"
                print(f"    - {label} [{f.get('type')}]: {clear_ft} ft  conf={conf}  "
                      f"interior_walls={interior}  note={f.get('code_note')}")
            draw.rectangle(box_px, outline=color, width=4)
            draw.text((box_px[0] + 5, max(0, box_px[1] - 14)), tag, fill=color)

        out_path = out_dir / f"page{pno}_vision.jpg"
        img.save(str(out_path), quality=85)
        print(f"    -> annotated image: {out_path}\n")

    doc.close()
    print(f"SUMMARY: {total_measured}/{total_feats} located features were measurable. "
          f"Open the annotated images in {out_dir} and check, box by box, that vision "
          f"pointed at the right feature and the number matches the drawing.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Live Phase-D vision measurement test (needs an API key).")
    ap.add_argument("pdf", help="path to a plan-set PDF")
    ap.add_argument("--pages", default="", help="comma-separated 1-based page numbers (default: auto-pick floor plans)")
    ap.add_argument("--out", default="./geometry_vision_out", help="output dir for annotated images")
    args = ap.parse_args()
    return asyncio.run(_run(args.pdf, args.pages, Path(args.out)))


if __name__ == "__main__":
    raise SystemExit(main())
