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
from pathlib import Path
from typing import Iterable, Mapping

from app.code_library.ingest.base import IngestTarget
from app.utils.logger import get_logger

logger = get_logger(__name__)

CORPUS_DIR = Path(__file__).resolve().parent.parent / "corpus"


def write_jsonl(target: IngestTarget, chunks: Iterable[Mapping]) -> Path:
    """Write the stream of chunk dicts to corpus/<target.output_filename>.
    Returns the absolute path of the file written. Overwrites in full —
    re-ingest replaces, it does not merge."""
    CORPUS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = CORPUS_DIR / target.output_filename
    count = 0
    with out_path.open("w", encoding="utf-8") as f:
        for c in chunks:
            f.write(json.dumps(c, ensure_ascii=False))
            f.write("\n")
            count += 1
    logger.info(f"[ingest] wrote {count} chunks → {out_path.name}")
    return out_path
