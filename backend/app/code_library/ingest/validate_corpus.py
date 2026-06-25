#!/usr/bin/env python3
"""Corpus health validator.

Walks the corpus/*.jsonl files and reports structural health so a truncated,
malformed, or empty ingest is caught before it silently degrades retrieval.
This is the read-side complement to writer.py's SHRINK_GUARD (which guards a
single re-ingest) and dedup_chunk_ids.py (which fixes duplicate ids in one
file) — neither gives a corpus-wide picture, which is what this provides.

It mirrors what corpus_loader._load_corpus_from_jsonl actually tolerates so it
never false-flags a file the loader reads fine: it skips // comment lines and
DERIVES a chunk_id ({code_short}-{section}, lowercased) when a row omits one,
exactly as the loader does. It checks only what lives in a chunk row; it does
NOT invent fields the schema doesn't carry (amendment effective dates live in
adoption_map.yaml, not in the chunks).

Severity:
  FAIL  - unparseable JSON line or empty/whitespace text. A real data defect
          (the loader silently drops bad JSON and an empty chunk pollutes
          retrieval); --strict exits non-zero when any FAIL is present.
  WARN  - THIN (below the chunk/byte floor — likely a truncated or image-only
          PDF that needs re-ingest) or DUP (the effective chunk_ids collide —
          for explicit ids run dedup_chunk_ids.py --fix; for derived ids the
          file has two rows sharing code_short+section). Reported, never fatal.
  OK    - parses clean, above the floor, unique effective ids.

Usage (from backend/):
    python -m app.code_library.ingest.validate_corpus
    python -m app.code_library.ingest.validate_corpus --min-chunks 3 --min-bytes 1500
    python -m app.code_library.ingest.validate_corpus --strict     # exit 1 on any FAIL
    python -m app.code_library.ingest.validate_corpus --include-superseded
"""
from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path
from typing import List, Optional

CORPUS_DIR = Path(__file__).resolve().parent.parent / "corpus"

# Defaults: a legitimately-short amendment (a one-section ordinance delta) is
# rare but real, so THIN is a warning, not a failure. The floors are tuned to
# catch the known truncations (Port Hueneme = 1 chunk / 2.6 KB) without
# false-flagging the small-but-complete reference stubs.
DEFAULT_MIN_CHUNKS = 3
DEFAULT_MIN_BYTES = 1500


class FileReport:
    def __init__(self, path: Path):
        self.path = path
        self.chunks = 0
        self.bytes = path.stat().st_size
        self.fails: List[str] = []   # FAIL-level defects (with line context)
        self.warns: List[str] = []   # WARN-level notes

    @property
    def status(self) -> str:
        if self.fails:
            return "FAIL"
        if self.warns:
            return "WARN"
        return "OK"


def _effective_id(obj: dict) -> str:
    """The id the loader will key on: explicit chunk_id, else the derived
    {code_short}-{section} (lowercased) — identical to corpus_loader."""
    cid = obj.get("chunk_id")
    if cid:
        return cid
    return f"{obj.get('code_short', '?')}-{obj.get('section', '?')}".lower()


def validate_file(path: Path, min_chunks: int, min_bytes: int) -> FileReport:
    rep = FileReport(path)
    ids = collections.Counter()
    derived_any = False
    with path.open(encoding="utf-8") as fh:
        for i, raw in enumerate(fh, 1):
            line = raw.strip()
            if not line or line.startswith("//"):
                continue  # blank / comment line — the loader skips these too
            rep.chunks += 1
            try:
                obj = json.loads(raw)
            except json.JSONDecodeError as e:
                rep.fails.append(f"line {i}: unparseable JSON ({e.msg})")
                continue
            if not obj.get("chunk_id"):
                derived_any = True
            ids[_effective_id(obj)] += 1
            if not (obj.get("text") or "").strip():
                rep.fails.append(f"line {i}: empty text (id {_effective_id(obj)})")

    dups = [cid for cid, n in ids.items() if n > 1]
    if dups:
        how = ("derived ids collide (rows share code_short+section)"
               if derived_any else "run dedup_chunk_ids.py --fix")
        rep.warns.append(f"DUP: {len(dups)} colliding chunk_id(s) — {how}")
    if rep.chunks < min_chunks or rep.bytes < min_bytes:
        rep.warns.append(
            f"THIN: {rep.chunks} chunk(s) / {rep.bytes:,} B "
            f"(floor {min_chunks} / {min_bytes:,}) — likely truncated; re-ingest"
        )
    return rep


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="validate_corpus")
    ap.add_argument("--min-chunks", type=int, default=DEFAULT_MIN_CHUNKS)
    ap.add_argument("--min-bytes", type=int, default=DEFAULT_MIN_BYTES)
    ap.add_argument("--include-superseded", action="store_true",
                    help="also scan corpus/_superseded/ (skipped by default)")
    ap.add_argument("--strict", action="store_true",
                    help="exit non-zero if any file has a FAIL-level defect")
    ap.add_argument("--corpus-dir", default=str(CORPUS_DIR))
    args = ap.parse_args(argv)

    corpus = Path(args.corpus_dir)
    if not corpus.is_dir():
        print(f"corpus dir not found: {corpus}", file=sys.stderr)
        return 2

    files = sorted(corpus.glob("*.jsonl"))
    if args.include_superseded:
        files += sorted(corpus.glob("_superseded/*.jsonl"))

    reports = [validate_file(p, args.min_chunks, args.min_bytes) for p in files]

    fails = [r for r in reports if r.status == "FAIL"]
    warns = [r for r in reports if r.status == "WARN"]
    flagged = fails + warns

    print("=" * 78)
    print(f"Corpus health: {len(files)} files, "
          f"{sum(r.chunks for r in reports):,} chunks, "
          f"{sum(r.bytes for r in reports):,} bytes")
    print(f"  OK {len(reports) - len(flagged)}  ·  WARN {len(warns)}  ·  FAIL {len(fails)}")
    print("=" * 78)
    if not flagged:
        print("  all files clean.")
    for r in sorted(flagged, key=lambda r: (r.status != "FAIL", r.path.name)):
        print(f"\n[{r.status}] {r.path.name}  ({r.chunks} chunks, {r.bytes:,} B)")
        for msg in r.fails + r.warns:
            print(f"    - {msg}")

    if args.strict and fails:
        print(f"\n=> STRICT: {len(fails)} file(s) with FAIL-level defects")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
