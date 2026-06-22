"""Step 6 — ingest the 2019 California Building Code as a NATIONAL-SCOPE model reference.

Per the user's decision: version tagged "2019" and jurisdictions=["*"] (a general
model-building-code reference, NOT an asserted adopted-CA-2025 citation), so a wrong-edition
provision can never masquerade as the governing CA building code. It's a deep replacement for
today's 16-chunk ibc_2021 stub for commercial building-safety review.

Scratch-first + quality report; promote to corpus/ only on an explicit --promote after the
report looks clean (the corpus loader globs corpus/*.jsonl, so scratch lives OUTSIDE it).

    .venv-claude/Scripts/python.exe -m scripts.step6_ingest_cbc
    .venv-claude/Scripts/python.exe -m scripts.step6_ingest_cbc --promote
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

from app.code_library.ingest.base import IngestTarget
from app.code_library.ingest.licensed_pdf import extract_pdf_text, parse_code_text
from app.code_library.ingest.chunker import chunk_many

BACKEND = Path(__file__).resolve().parent.parent
CORPUS_OUT = BACKEND / "app" / "code_library" / "corpus" / "cbc_2019.jsonl"
SCRATCH = BACKEND / "scratch" / "step6"
PDF = "C:/Users/evan marcarelli/Downloads/2019californiabu01unse.pdf"

_REPL = "�"


def _chapter(sec: str) -> str:
    m = re.match(r"[A-Z]?(\d+)", sec)
    if not m:
        return "?"
    d = m.group(1)
    return d[:-2] if len(d) >= 3 else d


def run(promote: bool) -> None:
    SCRATCH.mkdir(parents=True, exist_ok=True)
    target = IngestTarget(
        code_short="CBC", code_name="California Building Code",
        version="2019", jurisdictions=["*"], output_filename="cbc_2019.jsonl",
    )
    text = extract_pdf_text(PDF)
    sections = parse_code_text(text, source_url="file://2019californiabu01unse.pdf")
    chunks = list(chunk_many(sections, target))

    scratch = SCRATCH / "cbc_2019.jsonl"
    scratch.write_text("\n".join(json.dumps(c, ensure_ascii=False) for c in chunks) + "\n",
                       encoding="utf-8")

    # ---- quality report ----
    bad_id = [c for c in chunks if not c["chunk_id"].startswith("cbc-")]
    garbage = [c for c in chunks
               if _REPL in c["text"] or len(re.sub(r"[^A-Za-z]", "", c["text"])) < 12]
    lens = sorted(len(c["text"]) for c in chunks) or [0]
    chap = Counter(_chapter(c["section"]) for c in chunks)
    cats = Counter(c["category"] for c in chunks)

    print(f"sections parsed: {len(sections)}   chunks: {len(chunks)}")
    print(f"chunk_id 'cbc-' prefixed: {len(chunks) - len(bad_id)}/{len(chunks)}"
          + (f"  BAD: {[c['chunk_id'] for c in bad_id][:5]}" if bad_id else ""))
    print(f"suspected garbage (replacement-char / <12 letters): {len(garbage)} "
          f"({100*len(garbage)/max(1,len(chunks)):.1f}%)")
    print(f"body length: p10={lens[len(lens)//10]} median={lens[len(lens)//2]} max={lens[-1]}")
    print(f"category mix: {dict(cats.most_common())}")
    print("chapter coverage (chapter: chunk count):")
    for c in sorted(chap, key=lambda x: (len(x), x)):
        print(f"  Ch {c}: {chap[c]}")
    # WUI chapter 7A present? (deterministic WUI rules cite CBC 708A/709A)
    has7A = [c["section"] for c in chunks if re.match(r"7\d{2}A", c["section"])][:6]
    print(f"Ch 7A (WUI) sample sections: {has7A or 'NONE'}")
    print("\n-- 10 sampled provisions --")
    step = max(1, len(chunks) // 10)
    for c in chunks[::step][:10]:
        body = " ".join(c["text"].split())
        print(f"  [{c['section']:<10}] {c.get('title','')[:30]!r:<32} {body[:70]!r}")

    print(f"\nscratch: {scratch}")
    if promote:
        CORPUS_OUT.write_text(scratch.read_text(encoding="utf-8"), encoding="utf-8")
        print(f"PROMOTED -> {CORPUS_OUT} ({len(chunks)} chunks)")
    else:
        print("(report-only; pass --promote to write corpus/cbc_2019.jsonl)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--promote", action="store_true")
    run(ap.parse_args().promote)
