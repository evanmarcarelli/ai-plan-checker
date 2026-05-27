"""CLI entry point.

Run from the repo root with the backend on PYTHONPATH:

    cd backend
    python -m app.code_library.ingest amlegal --jurisdiction pasadena_ca
    python -m app.code_library.ingest amlegal --all              # every amlegal target
    python -m app.code_library.ingest amlegal --jurisdiction pasadena_ca --max 50  # cap for test runs

Output: one JSONL file per jurisdiction in backend/app/code_library/corpus/.
The corpus_loader.get_corpus() singleton picks them up on next process restart
(or call reload_corpus() explicitly).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Optional

import yaml

from app.code_library.ingest.base import IngestTarget
from app.utils.logger import get_logger

logger = get_logger(__name__)

CONFIG_PATH = Path(__file__).resolve().parent / "jurisdictions.yaml"


def _load_targets(source: str) -> List[dict]:
    """Read jurisdictions.yaml and return the entries for one source."""
    with CONFIG_PATH.open() as f:
        cfg = yaml.safe_load(f) or {}
    return cfg.get(source) or []


def _target_from_entry(entry: dict) -> IngestTarget:
    return IngestTarget(
        code_short=entry["code_short"],
        code_name=entry["code_name"],
        version=str(entry["version"]),
        jurisdictions=list(entry["jurisdictions"]),
        output_filename=entry["output_filename"],
    )


def cmd_amlegal(args: argparse.Namespace) -> int:
    from app.code_library.ingest.amlegal import ingest_amlegal_slug

    entries = _load_targets("amlegal")
    if args.jurisdiction:
        entries = [e for e in entries if e["source_id"] == args.jurisdiction]
        if not entries:
            print(f"No amlegal entry found for jurisdiction={args.jurisdiction!r}", file=sys.stderr)
            return 1
    elif not args.all:
        print("Pass --jurisdiction <slug> or --all", file=sys.stderr)
        return 2

    total = 0
    for entry in entries:
        slug = entry["source_id"]
        target = _target_from_entry(entry)
        try:
            written = ingest_amlegal_slug(slug, target, max_sections=args.max)
            logger.info(f"[amlegal] {slug}: wrote {written} chunks")
            total += written
        except Exception as e:
            logger.error(f"[amlegal] {slug} failed: {type(e).__name__}: {e}")
            if args.fail_fast:
                return 3
    logger.info(f"[amlegal] DONE. {total} chunks across {len(entries)} jurisdiction(s)")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    """Print the targets configured for each source."""
    with CONFIG_PATH.open() as f:
        cfg = yaml.safe_load(f) or {}
    for src, entries in cfg.items():
        print(f"\n[{src}] ({len(entries)} target{'s' if len(entries) != 1 else ''})")
        for e in entries:
            print(f"  {e['source_id']:24} {e['code_short']:18} -> {e['output_filename']}")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="app.code_library.ingest")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_am = sub.add_parser("amlegal", help="ingest from codelibrary.amlegal.com")
    g = p_am.add_mutually_exclusive_group()
    g.add_argument("--jurisdiction", help="source_id from jurisdictions.yaml (e.g. pasadena_ca)")
    g.add_argument("--all", action="store_true", help="ingest every amlegal jurisdiction in the yaml")
    p_am.add_argument("--max", type=int, default=None, help="cap sections per jurisdiction (test runs)")
    p_am.add_argument("--fail-fast", action="store_true", help="stop the batch on first jurisdiction failure")
    p_am.set_defaults(func=cmd_amlegal)

    p_ls = sub.add_parser("list", help="show configured targets")
    p_ls.set_defaults(func=cmd_list)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
