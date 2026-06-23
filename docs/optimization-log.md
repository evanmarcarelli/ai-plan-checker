# Optimization Log — Architechtura "City Hall for Development"

This is the **records department**: a version-controlled ledger of every optimization
the dev meta-system runs. It is *not* a notes vault — every row carries a measured
before/after so the loop can prove it made the product better, not just busier.

Appended by `/optimize` and `/postmortem`. One row per change. If a change regressed
the metric and was reverted, it still gets a row (kept = no) — negative results are
signal too.

## How to read a row

- **metric**: which number moved (e.g. `det_F1`, `citation_validity`, `critical_recall`, `cost/plan`, `latency`).
- **before → after**: measured via `/eval` (deterministic + benchmark dry are free/local; live needs a key).
- **kept**: yes = merged, no = reverted, pending = awaiting Evan's approval.
- **gate**: which harness measured it (`run_eval`, `benchmarks --dry`, `benchmarks --live`, `pytest`).

## Ledger

| date | department | change | metric | before → after | gate | kept | notes |
|---|---|---|---|---|---|---|---|
| 2026-06-22 | eval-engineer | baseline captured at meta-system install | det_F1 | — → 1.000 (P/R=1.000, archetype gate 20/20) | run_eval | — | Free local gate verified working on system python3. Open signal: 9 `wrong_status` soft pass↔warn↔info mismatches (F1 ignores these). benchmarks dry harness blocked on missing `tabulate` dep — install backend deps to enable the citation-validity gate. |
| 2026-06-22 | deterministic-engine | resolve 9 `wrong_status` soft mismatches (eval cases only, no engine change) | det_wrong_status | 9 → 0 (F1 held 1.000, archetype gate held 20/20, pytest 24 passed) | run_eval, pytest | yes | Root causes: (1) COM-AREA-ALLOWABLE x2 — harness extractor never read "Tenant area"; added recognized "Building area: N sf" line so engine returns true pass (B/II-A 37.5k limit vs 4.2k/3.8k). (2) COM-HIGH-RISE x2 — TI "Building height: existing" is genuinely undeclared; corrected expected pass→info (cannot evaluate the >75ft threshold). (3) COM-MIXED-OCCUPANCY x2 — rule does not exist in engine; a lone R-3 dwelling has no IBC 508 mixed-occupancy analysis; corrected pass→info. (4) FLS-ALARM x3 — rule gated off for R-3 (SFDs use CRC R310 smoke alarms, not NFPA 72 systems); corrected pass→info. 1 deliberately NOT touched: `--with-gate` F1 0.974 is a pre-existing corpus-thinness downgrade on wui-vhfhsz-deck-missing, unrelated. |
