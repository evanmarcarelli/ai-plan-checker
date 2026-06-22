"""Step 4 — non-destructive furniture-residue cleanup harness.

Re-parses a licensed code PDF through the HARDENED ingest parser and produces a
*diff-gated, conservative* repair of the existing corpus file: it only adopts a
re-ingested section when that section's body has strictly LESS page furniture
(folios, ">" breaks, ALL-CAPS running heads) while preserving substantially all
of the original substantive tokens. Everything else keeps the current text.

Why this shape (see plan zany-crunching-dusk.md):
  * A blind re-ingest/overwrite is unsafe — the hardened parser still misses a
    few sections (e.g. CEBC 319.7.4 -> an ALL-CAPS running head) and emits ~266
    new candidate sections of unknown quality.
  * Re-ingested chunks share source_tier="licensed" with the hand-authored
    ones, so load-time dedupe's length tiebreak would silently keep the wrong
    copy if two files ever coexisted. Therefore we decide every survivor
    explicitly and overwrite ONE file in place.

Outputs go to a scratch dir OUTSIDE corpus/ so the loader's corpus/*.jsonl glob
never picks them up. `--promote` is the only step that touches the live file.

Run from backend/ with the test venv:
    .venv-claude/Scripts/python.exe -m scripts.step4_furniture_harness --code CEBC
    .venv-claude/Scripts/python.exe -m scripts.step4_furniture_harness --code CEBC --promote
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Dict, List, Optional

from app.code_library.ingest.base import IngestTarget
from app.code_library.ingest.chunker import chunk_many, _normalize_text
from app.code_library.ingest.licensed_pdf import (
    _FURNITURE_RES,
    extract_pdf_text,
    parse_code_text,
)
from app.code_library.corpus_loader import tokenize

# ── config ───────────────────────────────────────────────────────────────
BACKEND = Path(__file__).resolve().parent.parent
CORPUS_DIR = BACKEND / "app" / "code_library" / "corpus"
SCRATCH = BACKEND / "scratch" / "step4"

CODES = {
    "CEBC": {
        "pdf": "C:/Users/evan marcarelli/Downloads/gov.ca.bsc.existing.2025.pdf",
        "file": "ca_cebc_2025.jsonl",
    },
    "CRC": {
        "pdf": "C:/Users/evan marcarelli/Downloads/gov.ca.bsc.residential.2025.pdf",
        "file": "ca_crc_2025.jsonl",
    },
}

RECALL_MIN = 0.98

# Hand-authored chunk_ids — derived from `git show 7e35840 e719f60 -- <cebc file>`.
# NEVER auto-replaced; surfaced in the report for eyeball only.
PROTECTED_IDS = {
    "cebc-310a.1.1.1", "cebc-310a.1.1.1.1", "cebc-310a.1.1.1.2", "cebc-310a.1.1.1.3",
    "cebc-310a.1.1.1.4", "cebc-310a.1.1.1.5", "cebc-313.6.1.4", "cebc-313.6.1.4.1",
    "cebc-313.6.1.4.2", "cebc-319.7", "cebc-319.7.1", "cebc-319.7.2", "cebc-319.7.3",
    "cebc-319.7.4", "cebc-319.7.5", "cebc-319.7.6", "cebc-319.7.7",
}

_ALLCAPS_LINE = re.compile(r"^[A-Z][A-Z0-9 \-/&,.\[\]]{7,}$")
# A hyphen page folio as a single token ("7-5"). En-dash ranges ("3–5") tokenize
# to separate "3"/"5" and are table VALUES, never folios — so they can never
# match this and a section that drops one is never treated as furniture-only.
_FOLIO_TOKEN = re.compile(r"^\d{1,2}-\d{1,3}$")


# ── signals ──────────────────────────────────────────────────────────────
def furniture_count(body: str) -> int:
    """Lines that look like page furniture: folios / ">" breaks (from the
    ingester's own regexes) plus ALL-CAPS running-head lines and dot leaders."""
    n = 0
    for rx in _FURNITURE_RES:
        n += len(rx.findall(body))
    for ln in body.splitlines():
        s = ln.strip()
        if _ALLCAPS_LINE.match(s) or "...." in s:
            n += 1
    return n


def _content_tokens(body: str) -> set:
    """Substantive tokens with furniture lines removed first, so furniture
    removal never lowers recall on its own."""
    kept = []
    for ln in body.splitlines():
        s = ln.strip()
        if _ALLCAPS_LINE.match(s) or "...." in s:
            continue
        if any(rx.match(s) for rx in _FURNITURE_RES):
            continue
        kept.append(ln)
    return set(tokenize(" ".join(kept)))


def token_recall(old: str, new: str) -> float:
    o = _content_tokens(old)
    if not o:
        return 1.0
    n = _content_tokens(new)
    return len(o & n) / len(o)


def looks_like_titlebleed(body: str) -> bool:
    """The whole body is a running head — e.g. 'PROVISIONS FOR ALL COMPLIANCE
    METHODS' (CEBC 319.7.4's residual parser miss)."""
    s = _normalize_text(body).strip()
    return bool(s) and len(s) < 80 and not re.search(r"[a-z]", s)


# ── load / parse ─────────────────────────────────────────────────────────
def load_current(path: Path):
    chunks = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
    by_section: Dict[str, List[dict]] = {}
    for c in chunks:
        by_section.setdefault(c["section"], []).append(c)
    return chunks, by_section


def target_from_current(chunks: List[dict]) -> IngestTarget:
    """Reuse the current file's exact metadata so re-ingested chunk_ids line up."""
    sample = chunks[0]
    return IngestTarget(
        code_short=sample["code_short"],
        code_name=sample["code_name"],
        version=sample["version"],
        jurisdictions=sample.get("jurisdictions") or ["*"],
        output_filename="__scratch__.jsonl",  # never used; we don't call write_jsonl
    )


def reingest(pdf: str, target: IngestTarget) -> Dict[str, List[dict]]:
    text = extract_pdf_text(pdf)
    sections = parse_code_text(text, source_url=f"file://{pdf}")
    new_chunks = list(chunk_many(sections, target))
    by_section: Dict[str, List[dict]] = {}
    for c in new_chunks:
        by_section.setdefault(c["section"], []).append(c)
    return by_section


# ── categorize ───────────────────────────────────────────────────────────
def categorize(section, old_chunks, new_chunks, code_short) -> str:
    cid = f"{code_short}-{section}".lower()
    if cid in PROTECTED_IDS or any(c["chunk_id"] in PROTECTED_IDS for c in (old_chunks or [])):
        return "PROTECTED"
    if not old_chunks:
        return "NEW"
    if not new_chunks:
        return "DROPPED"
    # Conservative: auto-improve only clean 1:1 sections (no split alignment).
    if len(old_chunks) != 1 or len(new_chunks) != 1:
        return "MULTI"  # keep current; surface in report
    old_b, new_b = old_chunks[0]["text"], new_chunks[0]["text"]
    if _normalize_text(old_b) == _normalize_text(new_b):
        return "UNCHANGED"
    f_old, f_new = furniture_count(old_b), furniture_count(new_b)
    # Table-safe gate, independent of the furniture-line heuristic: a genuine
    # furniture removal adds NO tokens and drops ONLY hyphen-folio tokens
    # ("7-5"). Any other dropped token (e.g. the bare "5" left when the
    # re-extraction blanked CRC R702.2.2.1's "3–5" table cell) or any added
    # token disqualifies it. This is stricter than a recall threshold, which
    # let that single lost table value slip through at recall 0.997.
    ot, nt = set(tokenize(old_b)), set(tokenize(new_b))
    dropped, added = ot - nt, nt - ot
    pure_folio_removal = (not added) and all(_FOLIO_TOKEN.match(t) for t in dropped)
    if looks_like_titlebleed(new_b) or f_new > f_old or not pure_folio_removal:
        return "REGRESSED"
    if len(_normalize_text(new_b)) > len(_normalize_text(old_b)):
        return "LONGER"  # content preserved but longer (over-merge/restore?) → review, keep current
    if f_new < f_old:
        return "IMPROVED"
    return "OTHER"  # changed but not clearly furniture removal → keep current


# ── main ─────────────────────────────────────────────────────────────────
def run(code: str, promote: bool) -> None:
    cfg = CODES[code]
    live = CORPUS_DIR / cfg["file"]
    SCRATCH.mkdir(parents=True, exist_ok=True)

    current, old_by = load_current(live)
    target = target_from_current(current)
    new_by = reingest(cfg["pdf"], target)

    sections = sorted(set(old_by) | set(new_by))
    cats: Dict[str, str] = {}
    for s in sections:
        cats[s] = categorize(s, old_by.get(s), new_by.get(s), target.code_short)

    counts: Dict[str, int] = {}
    for c in cats.values():
        counts[c] = counts.get(c, 0) + 1

    improved = [s for s in sections if cats[s] == "IMPROVED"]

    # Build merged candidate: preserve current order, swap IMPROVED sections.
    merged: List[dict] = []
    swapped = set()
    for ch in current:
        s = ch["section"]
        if s in set(improved):
            if s not in swapped:
                # keep old chunk's metadata; replace only the body text.
                base = dict(ch)
                base["text"] = new_by[s][0]["text"]
                merged.append(base)
                swapped.add(s)
        else:
            merged.append(ch)

    quarantine = [c for s in sections if cats[s] == "NEW" for c in new_by[s]]

    # ── write scratch artifacts (never into corpus/) ──
    cand = SCRATCH / f"{code.lower()}.merged.candidate.jsonl"
    quar = SCRATCH / f"{code.lower()}.new_sections.quarantine.jsonl"
    rep = SCRATCH / f"{code.lower()}.report.md"
    cand.write_text("\n".join(json.dumps(c, ensure_ascii=False) for c in merged) + "\n", encoding="utf-8")
    quar.write_text("\n".join(json.dumps(c, ensure_ascii=False) for c in quarantine) + "\n", encoding="utf-8")

    lines = [f"# Step 4 report — {code}", ""]
    lines.append(f"current chunks: {len(current)}  |  candidate chunks: {len(merged)}  "
                 f"|  quarantined NEW: {len(quarantine)}")
    lines.append(f"sections: current {len(old_by)}  re-parsed {len(new_by)}")
    lines.append("")
    lines.append("## category counts")
    for k in sorted(counts):
        lines.append(f"- {k}: {counts[k]}")
    lines.append("")
    lines.append("## IMPROVED (auto-applied — furniture removed, zero content-token loss, 1:1, not longer)")
    for s in improved:
        ob, nb = old_by[s][0]["text"], new_by[s][0]["text"]
        lines.append(f"\n### {s}  furniture {furniture_count(ob)}->{furniture_count(nb)}  "
                     f"recall {token_recall(ob, nb):.3f}  len {len(ob)}->{len(nb)}")
        lines.append(f"- OLD: {ob[:300]!r}")
        lines.append(f"- NEW: {nb[:300]!r}")
    for cat in ("REGRESSED", "LONGER", "MULTI", "DROPPED", "OTHER"):
        secs = [s for s in sections if cats[s] == cat]
        lines.append(f"\n## {cat} (kept current): {len(secs)}")
        for s in secs[:40]:
            ob = (old_by.get(s) or [{}])[0].get("text", "")
            nb = (new_by.get(s) or [{}])[0].get("text", "") if new_by.get(s) else "<none>"
            lines.append(f"- {s}: old[{len(ob)}] {ob[:80]!r}  ||  new[{len(nb) if nb!='<none>' else 0}] {nb[:80]!r}")
    prot = [s for s in sections if cats[s] == "PROTECTED"]
    lines.append(f"\n## PROTECTED (hand-authored, untouched): {len(prot)}")
    lines.append(", ".join(prot))
    rep.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"[{code}] current={len(current)} candidate={len(merged)} "
          f"improved={len(improved)} quarantined_new={len(quarantine)}")
    print("  category counts:", {k: counts[k] for k in sorted(counts)})
    print(f"  report:     {rep}")
    print(f"  candidate:  {cand}")
    print(f"  quarantine: {quar}")

    if promote:
        # In-place overwrite of the single live file (git-reversible). Refuse to
        # shrink — DROPPED keeps current, so count must be non-decreasing.
        if len(merged) < len(current):
            raise SystemExit(f"REFUSING to promote: candidate {len(merged)} < current {len(current)}")
        live.write_text("\n".join(json.dumps(c, ensure_ascii=False) for c in merged) + "\n",
                        encoding="utf-8")
        print(f"  PROMOTED -> {live} ({len(merged)} chunks)")
    else:
        print("  (report-only; pass --promote to overwrite the live file)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--code", required=True, choices=sorted(CODES))
    ap.add_argument("--promote", action="store_true")
    a = ap.parse_args()
    run(a.code, a.promote)
