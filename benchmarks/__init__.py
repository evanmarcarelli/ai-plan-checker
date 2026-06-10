"""Architechtura AI accuracy benchmark harness.

Two modes:

  python -m benchmarks                          # dry-run: schema + citation validity
  python -m benchmarks --live                   # run real pipeline (needs API key)
  python -m benchmarks --case altadena_sfr      # one case only
  python -m benchmarks --save-cache             # cache findings from live run
  python -m benchmarks --from-cache             # score cached findings (no API calls)

Why two modes? A live run is the only way to measure precision/recall on real
LLM output, but it costs real money. Dry-run gives an automated regression test
for the corpus + citation-verification wiring and runs in CI for free.
"""
