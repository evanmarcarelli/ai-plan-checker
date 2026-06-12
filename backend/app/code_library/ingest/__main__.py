"""CLI entry point.

Run from the repo root with the backend on PYTHONPATH:

    cd backend
    # one jurisdiction, capped for a test run
    python -m app.code_library.ingest amlegal   --jurisdiction pasadena_ca --max 50
    python -m app.code_library.ingest municode  --jurisdiction losangeles_ca --max 50
    python -m app.code_library.ingest qcode     --jurisdiction hermosabeach --max 50
    python -m app.code_library.ingest ecode360  --jurisdiction <slug>       --max 50

    # every target for one publisher
    python -m app.code_library.ingest amlegal  --all
    python -m app.code_library.ingest municode --all

    # every LA County jurisdiction across every publisher (the wedge)
    python -m app.code_library.ingest la-county

    # show every configured target
    python -m app.code_library.ingest list

Output: one JSONL file per jurisdiction in backend/app/code_library/corpus/.
The corpus_loader.get_corpus() singleton picks them up on next process restart
(or call reload_corpus() explicitly).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Callable, Dict, List, Optional

import yaml

from app.code_library.ingest.base import IngestTarget
from app.utils.logger import get_logger

logger = get_logger(__name__)

CONFIG_PATH = Path(__file__).resolve().parent / "jurisdictions.yaml"

# LA-County filter: a jurisdiction is in-scope when any of its scope strings
# matches one of these prefixes. Anything else is out (e.g. SF, San Diego).
LA_COUNTY_JURISDICTION_PREFIXES = (
    "CA:Los Angeles",          # LA city + LA County variants
    "CA:LA County",            # explicit unincorporated label
)
# These city names are the LA County 87 incorporated cities + the LA County
# unincorporated label. The prefix list above catches LA city; this set
# catches the rest.
LA_COUNTY_CITIES = {
    "Agoura Hills", "Alhambra", "Arcadia", "Artesia", "Avalon", "Azusa",
    "Baldwin Park", "Bell", "Bell Gardens", "Bellflower", "Beverly Hills",
    "Bradbury", "Burbank", "Calabasas", "Carson", "Cerritos", "Claremont",
    "Commerce", "Compton", "Covina", "Cudahy", "Culver City", "Diamond Bar",
    "Downey", "Duarte", "El Monte", "El Segundo", "Gardena", "Glendale",
    "Glendora", "Hawaiian Gardens", "Hawthorne", "Hermosa Beach",
    "Hidden Hills", "Huntington Park", "Industry", "Inglewood", "Irwindale",
    "La Cañada Flintridge", "La Habra Heights", "La Mirada", "La Puente",
    "La Verne", "Lakewood", "Lancaster", "Lawndale", "Lomita", "Long Beach",
    "Los Angeles", "Lynwood", "Malibu", "Manhattan Beach", "Maywood",
    "Monrovia", "Montebello", "Monterey Park", "Norwalk", "Palmdale",
    "Palos Verdes Estates", "Paramount", "Pasadena", "Pico Rivera",
    "Pomona", "Rancho Palos Verdes", "Redondo Beach", "Rolling Hills",
    "Rolling Hills Estates", "Rosemead", "San Dimas", "San Fernando",
    "San Gabriel", "San Marino", "Santa Clarita", "Santa Fe Springs",
    "Santa Monica", "Sierra Madre", "Signal Hill", "South El Monte",
    "South Gate", "South Pasadena", "Temple City", "Torrance", "Vernon",
    "Walnut", "West Covina", "West Hollywood", "Westlake Village",
    "Whittier",
}


def _load_targets(source: str) -> List[dict]:
    with CONFIG_PATH.open(encoding="utf-8") as f:
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


def _entry_is_la_county(entry: dict) -> bool:
    """True iff the entry's jurisdictions list places it inside LA County."""
    for j in entry.get("jurisdictions") or []:
        if any(j.startswith(p) for p in LA_COUNTY_JURISDICTION_PREFIXES):
            return True
        if ":" in j:
            _, city = j.split(":", 1)
            if city in LA_COUNTY_CITIES:
                return True
    return False


# ─────────────────────────────────────────────────────────────────────────
# Per-publisher commands
# ─────────────────────────────────────────────────────────────────────────


def _run_publisher(
    publisher: str,
    runner: Callable[[str, IngestTarget, Optional[int]], int],
    args: argparse.Namespace,
) -> int:
    entries = _load_targets(publisher)
    if args.jurisdiction:
        entries = [e for e in entries if e["source_id"] == args.jurisdiction]
        if not entries:
            print(
                f"No {publisher} entry found for jurisdiction={args.jurisdiction!r}",
                file=sys.stderr,
            )
            return 1
    elif not args.all:
        print("Pass --jurisdiction <slug> or --all", file=sys.stderr)
        return 2

    total = 0
    for entry in entries:
        slug = entry["source_id"]
        target = _target_from_entry(entry)
        try:
            written = runner(slug, target, args.max)
            logger.info(f"[{publisher}] {slug}: wrote {written} chunks")
            total += written
        except Exception as e:
            logger.error(f"[{publisher}] {slug} failed: {type(e).__name__}: {e}")
            if args.fail_fast:
                return 3
    logger.info(
        f"[{publisher}] DONE. {total} chunks across {len(entries)} jurisdiction(s)"
    )
    return 0


def cmd_amlegal(args: argparse.Namespace) -> int:
    from app.code_library.ingest.amlegal import ingest_amlegal_slug

    def runner(slug: str, target: IngestTarget, max_n: Optional[int]) -> int:
        return ingest_amlegal_slug(slug, target, max_sections=max_n)

    return _run_publisher("amlegal", runner, args)


def cmd_municode(args: argparse.Namespace) -> int:
    from app.code_library.ingest.municode import ingest_municode_slug

    def runner(slug: str, target: IngestTarget, max_n: Optional[int]) -> int:
        return ingest_municode_slug(slug, target, max_sections=max_n)

    return _run_publisher("municode", runner, args)


def cmd_qcode(args: argparse.Namespace) -> int:
    from app.code_library.ingest.qcode import ingest_qcode_slug

    def runner(slug: str, target: IngestTarget, max_n: Optional[int]) -> int:
        return ingest_qcode_slug(slug, target, max_sections=max_n)

    return _run_publisher("qcode", runner, args)


def cmd_ecode360(args: argparse.Namespace) -> int:
    from app.code_library.ingest.ecode360 import ingest_ecode360_slug

    def runner(slug: str, target: IngestTarget, max_n: Optional[int]) -> int:
        return ingest_ecode360_slug(slug, target, max_sections=max_n)

    return _run_publisher("ecode360", runner, args)


# ─────────────────────────────────────────────────────────────────────────
# LADBS (existing — public PDF publication path)
# ─────────────────────────────────────────────────────────────────────────


def cmd_ladbs(args: argparse.Namespace) -> int:
    from app.code_library.ingest.ladbs import KIND_SEEDS, ingest_ladbs

    kinds = [args.kind] if args.kind else list(KIND_SEEDS)
    total = 0
    for kind in kinds:
        try:
            written = ingest_ladbs(kind, max_docs=args.max)
            logger.info(f"[ladbs] {kind}: wrote {written} chunks")
            total += written
        except Exception as e:
            logger.error(f"[ladbs] {kind} failed: {type(e).__name__}: {e}")
            if args.fail_fast:
                return 3
    logger.info(f"[ladbs] DONE. {total} chunks across {len(kinds)} kind(s)")
    return 0


def cmd_ca_leginfo(args: argparse.Namespace) -> int:
    """Ingest curated California statute sections from the Legislature's own
    site (state-published law, no bot challenge, public domain)."""
    from app.code_library.ingest.ca_leginfo import ingest_ca_leginfo

    written = ingest_ca_leginfo(max_sections=args.max)
    logger.info(f"[ca-leginfo] wrote {written} chunks")
    return 0 if written else 4


def cmd_ca_coastal(args: argparse.Namespace) -> int:
    """Ingest the curated Coastal Act (PRC Div. 20) sections from leginfo,
    scoped to the CA:Coastal corpus layer."""
    from app.code_library.ingest.ca_leginfo import ingest_ca_coastal_act

    written = ingest_ca_coastal_act(max_sections=args.max)
    logger.info(f"[ca-coastal] wrote {written} chunks")
    return 0 if written else 4


def cmd_malibu_lip(args: argparse.Namespace) -> int:
    """Ingest the certified Malibu LCP Local Implementation Plan from the
    Coastal Commission's published PDF, scoped to CA:Malibu."""
    from app.code_library.ingest.malibu_lip import ingest_malibu_lip

    written = ingest_malibu_lip(pdf_path=args.pdf, max_sections=args.max)
    logger.info(f"[malibu-lip] wrote {written} chunks")
    return 0 if written else 4


def cmd_ada_gov(args: argparse.Namespace) -> int:
    """Ingest the complete 2010 ADA Standards from ada.gov (US government
    work — public domain)."""
    from app.code_library.ingest.ada_gov import ingest_ada_2010

    written = ingest_ada_2010(max_sections=args.max)
    logger.info(f"[ada-gov] wrote {written} chunks")
    return 0 if written else 4


def cmd_licensed_pdf(args: argparse.Namespace) -> int:
    """Ingest a locally-licensed model-code PDF (ICC purchase, state-published
    edition). The compliant path for IBC/CBC/CRC full text — no scraping."""
    from app.code_library.ingest.licensed_pdf import ingest_licensed_pdf

    target = IngestTarget(
        code_short=args.code_short,
        code_name=args.code_name,
        version=args.version,
        jurisdictions=args.scope or ["*"],
        output_filename=args.output
        or f"licensed_{args.code_short.lower().replace(' ', '_')}_{args.version}.jsonl",
    )
    written = ingest_licensed_pdf(
        args.pdf, target, max_pages=args.max_pages, max_sections=args.max
    )
    logger.info(f"[licensed-pdf] wrote {written} chunks for {args.code_short} {args.version}")
    return 0 if written else 4


def cmd_vcbc(args: argparse.Namespace) -> int:
    """Ingest the compiled Ventura County Building Code ordinance (county
    edict — Ord. 4655 adopts the 2025 Title 24 parts and amends them)."""
    from app.code_library.ingest.vcbc import ingest_vcbc

    written = ingest_vcbc(args.pdf, max_sections=args.max)
    logger.info(f"[vcbc] wrote {written} chunks")
    return 0 if written else 4


def cmd_ladbs_local(args: argparse.Namespace) -> int:
    import glob as _glob
    from app.code_library.ingest.ladbs import ingest_ladbs_files

    paths: list = []
    for d in args.dir or []:
        paths.extend(sorted(_glob.glob(f"{d.rstrip('/')}/*.pdf")))
    paths.extend(args.file or [])
    if not paths:
        print("Pass --dir <folder> and/or --file <pdf> (one or more)", file=sys.stderr)
        return 2
    written = ingest_ladbs_files(paths)
    logger.info(f"[ladbs-local] wrote/merged {written} new chunk(s) from {len(paths)} file(s)")
    return 0


# ─────────────────────────────────────────────────────────────────────────
# Umbrella: la-county
# ─────────────────────────────────────────────────────────────────────────


def cmd_la_county(args: argparse.Namespace) -> int:
    """Run every LA County target across every publisher.

    Order: amlegal first (most cities), then municode (LAMC + County + SE),
    then qcode (South Bay beach cities), then ecode360. LADBS is appended at
    the end because it depends on LA-city outputs being present for cross-ref.
    """
    publishers: List[tuple] = [
        ("amlegal",   "app.code_library.ingest.amlegal",   "ingest_amlegal_slug"),
        ("municode",  "app.code_library.ingest.municode",  "ingest_municode_slug"),
        ("qcode",     "app.code_library.ingest.qcode",     "ingest_qcode_slug"),
        ("ecode360",  "app.code_library.ingest.ecode360",  "ingest_ecode360_slug"),
    ]

    grand_total = 0
    grand_jurisdictions = 0
    for publisher, module_path, func_name in publishers:
        all_entries = _load_targets(publisher)
        la_entries = [e for e in all_entries if _entry_is_la_county(e)]
        if not la_entries:
            logger.info(f"[la-county] {publisher}: no LA County entries; skipping")
            continue

        runner = _import_runner(module_path, func_name)
        logger.info(
            f"[la-county] {publisher}: running {len(la_entries)} jurisdiction(s)"
        )
        for entry in la_entries:
            slug = entry["source_id"]
            target = _target_from_entry(entry)
            try:
                written = runner(slug, target, max_sections=args.max)
                logger.info(f"[la-county] {publisher}/{slug}: wrote {written} chunks")
                grand_total += written
                grand_jurisdictions += 1
            except Exception as e:
                logger.error(
                    f"[la-county] {publisher}/{slug} failed: {type(e).__name__}: {e}"
                )
                if args.fail_fast:
                    return 3

    # Roll in LADBS automatically — it's LA-specific by definition.
    if not args.skip_ladbs:
        from app.code_library.ingest.ladbs import KIND_SEEDS, ingest_ladbs
        for kind in KIND_SEEDS:
            try:
                written = ingest_ladbs(kind, max_docs=args.max)
                logger.info(f"[la-county] ladbs/{kind}: wrote {written} chunks")
                grand_total += written
            except Exception as e:
                logger.error(
                    f"[la-county] ladbs/{kind} failed: {type(e).__name__}: {e}"
                )
                if args.fail_fast:
                    return 3

    logger.info(
        f"[la-county] DONE. {grand_total} chunks across "
        f"{grand_jurisdictions} jurisdiction(s) + LADBS"
    )
    return 0


def _import_runner(module_path: str, func_name: str) -> Callable:
    import importlib

    mod = importlib.import_module(module_path)
    return getattr(mod, func_name)


# ─────────────────────────────────────────────────────────────────────────
# list
# ─────────────────────────────────────────────────────────────────────────


def cmd_list(args: argparse.Namespace) -> int:
    with CONFIG_PATH.open(encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    for src, entries in cfg.items():
        la_count = sum(1 for e in entries if _entry_is_la_county(e))
        print(
            f"\n[{src}] ({len(entries)} target{'s' if len(entries) != 1 else ''}, "
            f"{la_count} in LA County)"
        )
        for e in entries:
            tag = " [LA]" if _entry_is_la_county(e) else ""
            print(
                f"  {e['source_id']:28} {e['code_short']:18} -> {e['output_filename']}{tag}"
            )
    return 0


# ─────────────────────────────────────────────────────────────────────────
# main
# ─────────────────────────────────────────────────────────────────────────


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="app.code_library.ingest")
    sub = parser.add_subparsers(dest="cmd", required=True)

    # publisher commands share the same flag set
    for publisher, helptext, cmdfn in [
        ("amlegal",  "ingest from codelibrary.amlegal.com",  cmd_amlegal),
        ("municode", "ingest from library.municode.com",     cmd_municode),
        ("qcode",    "ingest from qcode.us",                 cmd_qcode),
        ("ecode360", "ingest from ecode360.com",             cmd_ecode360),
    ]:
        p = sub.add_parser(publisher, help=helptext)
        g = p.add_mutually_exclusive_group()
        g.add_argument(
            "--jurisdiction",
            help="source_id from jurisdictions.yaml (e.g. pasadena_ca)",
        )
        g.add_argument(
            "--all",
            action="store_true",
            help=f"ingest every {publisher} jurisdiction in the yaml",
        )
        p.add_argument(
            "--max",
            type=int,
            default=None,
            help="cap sections per jurisdiction (test runs)",
        )
        p.add_argument(
            "--fail-fast",
            action="store_true",
            help="stop the batch on first jurisdiction failure",
        )
        p.set_defaults(func=cmdfn)

    # ladbs (publication PDFs) — unchanged
    p_la = sub.add_parser("ladbs", help="ingest public LADBS publications (dbs.lacity.gov)")
    p_la.add_argument(
        "--kind",
        choices=["bulletins", "corrections", "amendments"],
        help="which LADBS publication set (default: all)",
    )
    p_la.add_argument("--max", type=int, default=None, help="cap docs per kind")
    p_la.add_argument("--fail-fast", action="store_true")
    p_la.set_defaults(func=cmd_ladbs)

    p_cl = sub.add_parser(
        "ca-leginfo",
        help="ingest curated CA statutes (Gov Code 51182 VHFSZ, PRC 4291, "
             "ADU law) from leginfo.legislature.ca.gov — official, no Cloudflare",
    )
    p_cl.add_argument("--max", type=int, default=None, help="cap sections (test runs)")
    p_cl.set_defaults(func=cmd_ca_leginfo)

    p_cc = sub.add_parser(
        "ca-coastal",
        help="ingest curated Coastal Act sections (PRC Div. 20) from leginfo, "
             "scoped to the CA:Coastal layer (coastal-zone projects only)",
    )
    p_cc.add_argument("--max", type=int, default=None, help="cap sections (test runs)")
    p_cc.set_defaults(func=cmd_ca_coastal)

    p_ml = sub.add_parser(
        "malibu-lip",
        help="ingest the certified Malibu LCP Local Implementation Plan "
             "(coastal.ca.gov PDF — government edict), scoped to CA:Malibu",
    )
    p_ml.add_argument("--pdf", help="local LIP PDF path (default: download/cache)")
    p_ml.add_argument("--max", type=int, default=None, help="cap sections (test runs)")
    p_ml.set_defaults(func=cmd_malibu_lip)

    p_ag = sub.add_parser(
        "ada-gov",
        help="ingest the complete 2010 ADA Standards from ada.gov (public domain)",
    )
    p_ag.add_argument("--max", type=int, default=None, help="cap sections (test runs)")
    p_ag.set_defaults(func=cmd_ada_gov)

    p_lic = sub.add_parser(
        "licensed-pdf",
        help="ingest a locally-licensed model-code PDF (ICC purchase / "
             "state-published edition) — the compliant IBC/CBC/CRC path",
    )
    p_lic.add_argument("--pdf", required=True, help="path to the licensed code PDF")
    p_lic.add_argument("--code-short", required=True, help='e.g. "IBC", "CBC", "CRC"')
    p_lic.add_argument("--code-name", required=True,
                       help='e.g. "International Building Code"')
    p_lic.add_argument("--version", required=True, help='edition, e.g. "2021"')
    p_lic.add_argument(
        "--scope", action="append",
        help='jurisdiction tag (repeatable), e.g. "*" or "CA" (default "*")',
    )
    p_lic.add_argument("--output", help="corpus filename (default licensed_<code>_<ver>.jsonl)")
    p_lic.add_argument("--max-pages", type=int, default=None, help="cap PDF pages (test runs)")
    p_lic.add_argument("--max", type=int, default=None, help="cap sections (test runs)")
    p_lic.set_defaults(func=cmd_licensed_pdf)

    p_vc = sub.add_parser(
        "vcbc",
        help="ingest the compiled Ventura County Building Code ordinance "
             "(Ord. 4655 PDF — county edict), scoped to CA:Ventura County",
    )
    p_vc.add_argument("--pdf", required=True, help="local VCBC ordinance PDF path")
    p_vc.add_argument("--max", type=int, default=None, help="cap sections (test runs)")
    p_vc.set_defaults(func=cmd_vcbc)

    p_ll = sub.add_parser(
        "ladbs-local", help="ingest hand-downloaded LADBS bulletin PDFs (no scraping)"
    )
    p_ll.add_argument("--dir", action="append", help="folder of *.pdf (repeatable)")
    p_ll.add_argument("--file", action="append", help="a single PDF (repeatable)")
    p_ll.set_defaults(func=cmd_ladbs_local)

    # la-county umbrella
    p_lc = sub.add_parser(
        "la-county",
        help="run every LA County target across every publisher + LADBS",
    )
    p_lc.add_argument(
        "--max",
        type=int,
        default=None,
        help="cap sections per jurisdiction (test runs)",
    )
    p_lc.add_argument("--fail-fast", action="store_true")
    p_lc.add_argument(
        "--skip-ladbs",
        action="store_true",
        help="skip the LADBS publication ingest step",
    )
    p_lc.set_defaults(func=cmd_la_county)

    # list
    p_ls = sub.add_parser("list", help="show configured targets")
    p_ls.set_defaults(func=cmd_list)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
