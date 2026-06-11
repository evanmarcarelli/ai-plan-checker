"""JSONL writer.

Drops scraped chunks alongside the curated ones in
backend/app/code_library/corpus/. The corpus loader picks them up on next
import via its `*.jsonl` glob; no additional registration needed.

We deliberately KEEP scraped files separately from curated files
(`amlegal_<slug>.jsonl` vs e.g. `ada_2010.jsonl`) so a re-ingest blows
away only the scraped half and the hand-curated baseline stays pristine.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Iterable, Mapping

from app.code_library.ingest.base import IngestTarget
from app.utils.logger import get_logger

logger = get_logger(__name__)

CORPUS_DIR = Path(__file__).resolve().parent.parent / "corpus"

# Refuse to replace an existing corpus file with one less than this fraction
# of its size (in chunks). Catches the "capped test run (--max 25) silently
# replaced a 233-chunk corpus with 13 chunks" footgun. Override deliberately
# with INGEST_ALLOW_SHRINK=1 when a real re-ingest legitimately shrinks.
SHRINK_GUARD_RATIO = 0.5


def write_jsonl(target: IngestTarget, chunks: Iterable[Mapping]) -> Path:
    """Write the stream of chunk dicts to corpus/<target.output_filename>.
    Returns the absolute path of the file written. Overwrites in full —
    re-ingest replaces, it does not merge.

    Safety: a scrape that yields ZERO chunks (site blocked, markup drift,
    Cloudflare challenge) MUST NOT clobber a previously-good corpus file with
    an empty one. When chunks is empty we refuse to write and leave any
    existing file intact, so a transient block can't silently wipe the corpus.
    Writes go to a temp file first and are atomically renamed, so a crash
    mid-write also can't leave a half-written file in place.
    """
    CORPUS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = CORPUS_DIR / target.output_filename

    materialized = list(chunks)
    if not materialized:
        existing = out_path.exists()
        logger.error(
            f"[ingest] 0 chunks for {out_path.name} — refusing to overwrite. "
            f"{'Existing file left intact.' if existing else 'No file written.'} "
            f"Likely cause: source blocked the scraper (e.g. Cloudflare challenge) "
            f"or its HTML structure drifted."
        )
        return out_path

    # Shrink guard: a capped or partially-blocked run must not replace a
    # bigger previously-good file. (The zero-chunk case above is the extreme
    # of the same failure.)
    if out_path.exists() and os.environ.get("INGEST_ALLOW_SHRINK") != "1":
        try:
            existing_count = sum(
                1 for line in out_path.open(encoding="utf-8") if line.strip()
            )
        except Exception:
            existing_count = 0
        if existing_count and len(materialized) < existing_count * SHRINK_GUARD_RATIO:
            logger.error(
                f"[ingest] refusing to replace {out_path.name} "
                f"({existing_count} chunks) with only {len(materialized)} chunks "
                f"(<{SHRINK_GUARD_RATIO:.0%}). If this shrink is intentional, "
                f"set INGEST_ALLOW_SHRINK=1 and re-run."
            )
            return out_path

    tmp_path = out_path.with_suffix(out_path.suffix + ".tmp")
    count = 0
    with tmp_path.open("w", encoding="utf-8") as f:
        for c in materialized:
            f.write(json.dumps(c, ensure_ascii=False))
            f.write("\n")
            count += 1
    tmp_path.replace(out_path)  # atomic on the same filesystem
    logger.info(f"[ingest] wrote {count} chunks → {out_path.name}")
    return out_path
