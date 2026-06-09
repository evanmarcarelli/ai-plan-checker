"""Backfill the structured corpus (migration 008) from the existing JSONL.

One-time / re-runnable migration of app/code_library/corpus/*.jsonl into the
Postgres code_chunks (+ code_editions) tables. Idempotent: upserts on
chunk_id, so running it twice is a no-op and re-running after editing a JSONL
updates in place.

    python -m scripts.ingest.jsonl_to_postgres --dry-run        # show plan
    python -m scripts.ingest.jsonl_to_postgres                  # write
    python -m scripts.ingest.jsonl_to_postgres --limit 50       # smoke test

It deliberately writes the DENORMALIZED read surface (code_chunks). Populating
the normalized provisions/amendments tree is a separate, structured ingest
(those tables exist in 008 for lineage + future automated diffing).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

from app.code_library.corpus_loader import CORPUS_DIR, CodeChunk
from app.code_library import structure
from app.utils.logger import get_logger

logger = get_logger(__name__)

# Coarse provenance defaults by code. Refine per-source as real licensing/source
# tiers are confirmed; this at least stops everything defaulting to "unknown".
PROVENANCE: Dict[str, Dict[str, str]] = {
    "LADBS-IB": {"source_tier": "official_gov", "license_status": "edict"},
    "T24":      {"source_tier": "official_gov", "license_status": "edict"},
    "CBC":      {"source_tier": "official_gov", "license_status": "edict"},
    "ADA":      {"source_tier": "official_gov", "license_status": "edict"},
    # Model codes — commercial use needs a license decision; flag for review.
    "IBC":      {"source_tier": "unspecified", "license_status": "fair_use_review"},
    "IFC":      {"source_tier": "unspecified", "license_status": "fair_use_review"},
    "IPC":      {"source_tier": "unspecified", "license_status": "fair_use_review"},
    "IMC":      {"source_tier": "unspecified", "license_status": "fair_use_review"},
    "NEC":      {"source_tier": "unspecified", "license_status": "fair_use_review"},
}


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _chunk_to_row(c: CodeChunk) -> Dict[str, Any]:
    path = structure.section_to_ltree(c.section)
    adoption_id = structure.adoption_id_for_chunk(c.jurisdictions)
    parent = structure.parent_section(c.section)
    # Flat source -> we only know this node's own heading; richer ancestor
    # headers come later from the structured (tree) ingest.
    header = structure.build_context_header(
        c.code_short, c.version, ancestors=[], section=c.section, heading=c.title
    )
    prov = PROVENANCE.get(c.code_short, {"source_tier": "unspecified", "license_status": "review"})
    return {
        "chunk_id": c.chunk_id,
        "adoption_id": adoption_id,
        "edition_id": f"{c.code_short}:{c.version}",
        "code_short": c.code_short,
        "version": c.version,
        "section": c.section,
        "path": path,
        "parent_section": parent,
        "citation": c.citation,
        "discipline": c.category,
        "heading": c.title or None,
        "context_header": header,
        "body": c.text,
        "jurisdictions": c.jurisdictions or [],
        "tags": c.tags or [],
        "source_tier": prov["source_tier"],
        "license_status": prov["license_status"],
        "content_sha256": _sha256(c.text or ""),
    }


def _read_jsonl() -> List[CodeChunk]:
    chunks: List[CodeChunk] = []
    for fp in sorted(CORPUS_DIR.glob("*.jsonl")):
        with fp.open() as f:
            for lineno, line in enumerate(f, 1):
                line = line.strip()
                if not line or line.startswith("//"):
                    continue
                try:
                    raw = json.loads(line)
                except json.JSONDecodeError as e:
                    logger.error(f"{fp.name}:{lineno} bad JSON: {e}")
                    continue
                raw.setdefault("chunk_id",
                               f"{raw.get('code_short','?')}-{raw.get('section','?')}".lower())
                try:
                    chunks.append(CodeChunk(**raw))
                except Exception as e:
                    logger.error(f"{fp.name}:{lineno} bad chunk: {e}")
    return chunks


def _editions_from(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        eid = r["edition_id"]
        if eid not in seen:
            seen[eid] = {
                "id": eid,
                "publisher": r["code_short"],
                "title": r["code_short"],
                "source_tier": r["source_tier"],
                "license_status": r["license_status"],
            }
    return list(seen.values())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="print plan, write nothing")
    ap.add_argument("--limit", type=int, default=None, help="only process N chunks")
    ap.add_argument("--batch", type=int, default=200)
    args = ap.parse_args()

    chunks = _read_jsonl()
    if args.limit:
        chunks = chunks[: args.limit]
    rows = [_chunk_to_row(c) for c in chunks]
    editions = _editions_from(rows)

    logger.info(f"Parsed {len(rows)} chunks across {len(editions)} editions")
    if rows:
        sample = rows[0]
        logger.info(f"Sample: {sample['citation']}  path={sample['path']}  "
                    f"adoption={sample['adoption_id']}  license={sample['license_status']}")
    # Surface unscoped license risks early (the legal point from the plan).
    review = sorted({r["edition_id"] for r in rows if r["license_status"] == "fair_use_review"})
    if review:
        logger.warning(f"License review needed for editions: {', '.join(review)}")

    if args.dry_run:
        logger.info("--dry-run: nothing written")
        return 0

    from app.services import db
    client = db.admin()

    client.table("code_editions").upsert(editions, on_conflict="id").execute()
    logger.info(f"Upserted {len(editions)} editions")

    written = 0
    for i in range(0, len(rows), args.batch):
        chunk = rows[i:i + args.batch]
        client.table("code_chunks").upsert(chunk, on_conflict="chunk_id").execute()
        written += len(chunk)
        logger.info(f"Upserted {written}/{len(rows)} chunks")

    logger.info("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
