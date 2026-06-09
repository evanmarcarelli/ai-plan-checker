"""Build the normalized provision tree (migration 008 `provisions`) from the corpus.

The corpus is leaf-only (e.g. IBC 1004.1.1) with no interior nodes, so ancestor
expansion has nothing to climb. This derives the tree from each leaf's ltree
path: it materializes the chapter / section / subsection ancestors (with real
headings where a chunk supplies one, generic 'Chapter N' otherwise) so
get_provision_ancestors can return a real breadcrumb — the structural fix for
"this exception only means something inside Chapter 10."

Honest limitation: interior nodes we don't have a chunk for carry the number +
a generic heading and NO verbatim text (we don't have licensed full chapter
text). The structure is real; the prose for un-sourced ancestors is not.

    python -m scripts.ingest.build_provisions --dry-run
    python -m scripts.ingest.build_provisions
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict, List

from app.code_library.corpus_loader import CORPUS_DIR, CodeChunk
from app.code_library import structure
from app.utils.logger import get_logger

logger = get_logger(__name__)


def build_provision_rows(chunks: List[CodeChunk]) -> List[Dict[str, Any]]:
    """Pure: derive provision tree rows (one per distinct edition+path) from
    leaf chunks. A real chunk's row always wins over a derived ancestor."""
    by_key: Dict[tuple, Dict[str, Any]] = {}
    for c in chunks:
        edition = f"{c.code_short}:{c.version}"
        full = structure.section_to_ltree(c.section)
        labels = full.split(".")
        prefixes = structure.ancestor_paths(full)
        for depth, sub in enumerate(prefixes):
            label = labels[depth]
            is_leaf = depth == len(prefixes) - 1
            key = (edition, sub)
            parent = ".".join(labels[:depth]) or None
            number = structure.path_label_to_number(label)
            kind = structure.provision_kind(label, depth, is_leaf)
            if is_leaf:
                by_key[key] = {                       # real chunk wins
                    "edition_id": edition, "path": sub, "parent_path": parent,
                    "number": number, "kind": kind,
                    "heading": c.title or None, "text": c.text,
                }
            elif key not in by_key:
                by_key[key] = {                       # derived interior node
                    "edition_id": edition, "path": sub, "parent_path": parent,
                    "number": number, "kind": kind,
                    "heading": f"Chapter {number}" if kind == "chapter" else None,
                    "text": None,
                }
    return list(by_key.values())


def _editions_from(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        eid = r["edition_id"]
        if eid not in out:
            short = eid.split(":")[0]
            out[eid] = {"id": eid, "publisher": short, "title": short}
    return list(out.values())


def _read_jsonl() -> List[CodeChunk]:
    chunks: List[CodeChunk] = []
    for fp in sorted(CORPUS_DIR.glob("*.jsonl")):
        with fp.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("//"):
                    continue
                try:
                    raw = json.loads(line)
                except json.JSONDecodeError:
                    continue
                raw.setdefault("chunk_id",
                               f"{raw.get('code_short','?')}-{raw.get('section','?')}".lower())
                try:
                    chunks.append(CodeChunk(**raw))
                except Exception:
                    pass
    return chunks


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--batch", type=int, default=200)
    args = ap.parse_args()

    rows = build_provision_rows(_read_jsonl())
    editions = _editions_from(rows)
    kinds: Dict[str, int] = {}
    for r in rows:
        kinds[r["kind"]] = kinds.get(r["kind"], 0) + 1
    logger.info(f"Built {len(rows)} provisions across {len(editions)} editions: "
                + ", ".join(f"{k}={v}" for k, v in sorted(kinds.items())))

    if args.dry_run:
        logger.info("--dry-run: nothing written")
        return 0

    from app.services import db
    client = db.admin()
    client.table("code_editions").upsert(editions, on_conflict="id").execute()
    written = 0
    for i in range(0, len(rows), args.batch):
        batch = rows[i:i + args.batch]
        client.table("provisions").upsert(batch, on_conflict="edition_id,path").execute()
        written += len(batch)
        logger.info(f"Upserted {written}/{len(rows)} provisions")
    logger.info("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
