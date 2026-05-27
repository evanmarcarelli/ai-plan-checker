"""Code-corpus ingestion pipeline.

Public surface (a single CLI plus three building blocks):

  python -m app.code_library.ingest amlegal --jurisdiction pasadena_ca
  python -m app.code_library.ingest amlegal --all-ca

  from app.code_library.ingest import chunk_section, write_jsonl

What this does, in one sentence: pulls public municipal/state code text from
American Legal Publishing (and stub-supported Municode / eCode360), splits it
into citable chunks keyed by section number, runs a keyword classifier to
tag each chunk with a `category`, and writes JSONL files into
backend/app/code_library/corpus/ where the existing BM25 retriever picks
them up automatically.

Why we are NOT touching the existing curated chunks: those are reviewed and
trusted. The scraped chunks live in their own files (`amlegal_<slug>.jsonl`)
so they can be regenerated, deleted, or version-pinned without disturbing
the hand-built baseline.
"""
from app.code_library.ingest.chunker import chunk_section, classify_category
from app.code_library.ingest.writer import write_jsonl

__all__ = ["chunk_section", "classify_category", "write_jsonl"]
