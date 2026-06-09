# Accuracy Benchmark — Design & Program

The job of this benchmark is to answer **one** question with a defensible number:

> *Can we ship this to a paying architect, and what may we honestly claim it does?*

Everything below serves that decision. This document is the design; the existing
`benchmarks/` harness (runner/scorer + the README's metrics) is the seed we build
on. Nothing here throws that away — it extends it.

---

## 0. What you already have (and the gaps)

**Have (keep):** dry/live/cache modes; citation-validity, critical-recall,
precision/recall/F1, forbidden-hits; a calibration table with v1 + ship targets;
a clean `ground_truth.yaml` + `plan_features.yaml` per case.

**Gaps (what this design fixes):**
1. **2 cases, both synthetic** — no statistical power, no real-world signal.
2. **`plan_features.yaml` bypasses the Surveyor** — extraction (vision/OCR/regex)
   is your #1 real failure source and it is currently *untested* end to end.
3. **Exact-section matching is brittle** — an examiner's `CBC 1011.5.2` vs the
   AI's `IBC 1011.5` is the *same issue, zero match*. You'll under-credit.
4. **No ground-truth methodology** — who labels, how subjectivity is handled,
   whether the labels are even self-consistent.
5. **No stage decomposition** — a miss could be extraction, retrieval, or
   reasoning; today you can't tell which, so you can't fix the right thing.
6. **No statistical rigor** — 2 cases supports zero claims; no CIs, no holdout.
7. **No variance / cost tracking** — LLMs are nondeterministic and metered.

---

## 1. Principles (non-negotiable)

- **Recall on life-safety > everything.** A missed critical finding is the
  catastrophic, liability-creating failure. Precision protects trust; *recall on
  critical findings protects the company.* They are weighted differently (below).
- **Frozen holdout or it's a lie.** A set you never look at while tuning prompts,
  models, or corpus. The holdout number is the only one you quote externally.
- **Test the whole pipe, including extraction.** Synthetic features measure your
  *assumptions* about plans; real PDFs measure reality. Both, explicitly labeled.
- **Honest denominators.** "Recall" is recall *of labeled findings*. Ground truth
  (even a city's correction letter) is incomplete; never pretend otherwise.
- **A finding is the unit, matching is semantic.** Score issues, not strings.
- **Every run is reproducible.** Pin git SHA + model ids + corpus hash + seed.

---

## 2. The ground-truth problem (the crux — read this twice)

Accuracy is only as real as the labels. Three tiers, used together:

| Tier | Source | Tests | Cost | Use |
|---|---|---|---|---|
| **A — Seeded/synthetic** | Hand-authored features + injected known defects (what you have) | Engine + reasoning, *not* extraction | Cheap | Regression + objective-violation recall; CI |
| **B — Expert-labeled real PDFs** | Real plan sets, labeled by a licensed plan checker/architect | **Full pipeline incl. extraction** | Medium | The credible accuracy number; the holdout |
| **C — Real correction letters (gold)** | Real plans paired with the AHJ's *actual* issued corrections | Pipeline vs the real world | Hard to source | The unimpeachable number; sales/legal proof |

**Two truths that shape the whole scoring design:**

1. **Incomplete ground truth.** The AI may flag a *real* issue the labeler (or
   even the city) missed. So an unmatched prediction is **"unconfirmed," not
   automatically a false positive** — it goes to adjudication. Otherwise you
   punish the model for being thorough.
2. **Subjectivity ceiling.** Plan check is partly judgment; two examiners
   disagree. **Measure inter-rater agreement (Cohen's κ) on an overlap set.**
   That agreement is the *ceiling* — the AI cannot be "more correct" than humans
   are consistent. Split findings into **hard** (objective: area > table, door <
   32") and **soft** (judgment) and score them separately. Hard findings demand
   near-perfect recall; soft findings are graded against the *set* of acceptable
   labeler answers, not a single point.

**Sourcing Tier C realistically:** partner with one expediter or production-home
firm. They have stacks of (plan set → city correction letter) pairs and a direct
incentive (you shorten their resubmittal cycles). 20 such pairs is worth more
than 200 synthetic cases.

---

## 3. Dataset design

**Stratify** so you can make *per-segment* claims, not one mushy average:

- Jurisdiction: LA City, LA County, San Diego, Ventura, …
- Occupancy: R-3, B, A-2, M, … (your live targets first)
- Construction type: V-B, II-B, …
- Project type: new / tenant-improvement / rebuild
- **Defect profile:** *compliant* (0 expected findings — measures false-positive
  rate, a control you currently lack), *single-defect*, *multi-defect*
- **Input quality:** clean vector PDF / scanned / mixed / missing-title-sheet
  (extraction stress tests)
- Complexity: page count, # of disciplines in scope

**Controls are mandatory.** Include known-**clean** plans. A system that flags
problems on a compliant set is worse than useless — and synthetic-defect-only
benchmarks never catch that.

**Size & power (rough targets):**
- Tier A: ≥ 5 cases per (occupancy × defect-type) cell you care about.
- Tier B: **≥ 100 real plans**, ≥ 30 per stratum you want to quote, yielding
  **≥ 200 labeled findings** total (precision/recall CIs stay wide below this).
- Critical-recall claim needs **≥ ~30 critical findings** in the set, or the CI
  is meaningless. Report all metrics with **bootstrap 95% CIs** — "0.86 ± 0.09
  (n=42)" not "86%".

**Splits:**
- **`dev`** — iterate freely (prompts, corpus, models).
- **`holdout`** — sealed. Run only at release / major model or corpus change.
  Tune *anything* against it and it's burned. Expand it deliberately over time;
  never delete cases you've "passed."

---

## 4. Labeling protocol

- **Labelers:** ≥ 1 licensed CA plan checker / architect with real plan-check
  experience. For the **holdout**, ≥ 2 labelers on a ≥ 30% overlap to compute κ.
- **Inter-rater step:** report finding-level agreement + Cohen's κ. If κ on soft
  findings is, say, < 0.6, treat soft findings as a *graded* bucket, not pass/fail.
- **Adjudication:** a senior reviewer resolves labeler disagreements and
  adjudicates the AI's *unmatched* predictions into {true-but-unlabeled,
  false-positive, out-of-scope}.

**Extended label schema** (superset of your current `ground_truth.yaml`):

```yaml
case_id: altadena_sfr_rebuild
tier: B                      # A | B | C
split: holdout               # dev | holdout
source: "LA County correction letter 2025-04-12"   # provenance
jurisdiction: { state: CA, county: Los Angeles, city: Altadena }
plan_type: residential
input_quality: vector        # vector | scanned | mixed | missing_title_sheet
labelers: [jc_pe, ms_arch]   # ≥2 for holdout overlap
expected_findings:
  - issue_id: wui-siding-5ft        # stable id, NOT the section string
    acceptable_sections:            # ANY of these citations counts as correct
      - "CBC-7A 704A.1"
      - "CRC R337.7"
    plan_element: "exterior wall < 5ft of grade"
    objectivity: soft               # hard | soft
    severity: critical
    status: non_compliant           # non_compliant | needs_review
    acceptance_criteria: >          # what a CORRECT AI finding must convey
      Flags combustible siding in the first 5 ft and/or non-ember-resistant
      vents in a VHFHSZ. Citing the right intent counts even if subsection differs.
    location: { sheet: "A-3.1", note: "south elevation" }
must_not_flag:                       # hard false-positive guards
  - "ADA 208.2"                      # accessible parking — irrelevant to an SFR
```

The three changes that make scoring tractable: **`issue_id`** (match on issues,
not strings), **`acceptable_sections`** (a *set* of correct citations), and
**`acceptance_criteria`** (lets an LLM/human judge a semantic match).

---

## 5. The matching rubric (where most benchmarks quietly cheat)

Bipartite-match predicted findings `P` to ground-truth findings `G` in tiers,
most-confident first; once a `g` or `p` is matched it's consumed:

1. **Exact / family section match.** Normalize (strip code prefix; compare
   section family via the `ltree` ancestry we built). `IBC 1011.5.2` ↔ acceptable
   `IBC 1011.5` → candidate match.
2. **Plan-element + category match.** Same element ("egress door width") + same
   discipline, different section → candidate.
3. **LLM-judge adjudication.** For remaining candidates, an LLM judge answers
   *"Do these describe the same code issue, per the acceptance_criteria?"* (cheap,
   logged, spot-checked by a human on the holdout).
4. **Human adjudication.** Holdout only: a person confirms ambiguous matches and
   classifies every *unmatched prediction*.

**Outcome taxonomy per finding:**

| Bucket | Meaning | Counts as |
|---|---|---|
| **TP** | predicted matched a GT finding, status compatible | hit |
| **TP-sev** | matched issue, **wrong severity/status** | hit, but severity-error tracked |
| **FN** | GT finding with no prediction | **miss** (the dangerous one) |
| **FP-confirmed** | unmatched prediction, adjudicated *wrong* | false alarm |
| **FP-unlabeled** | unmatched prediction, adjudicated *real but unlabeled* | excluded from precision denom; logged as "bonus" |
| **Forbidden** | hit a `must_not_flag` item | **hard false positive** (regression bug) |

Status compatibility: `non_compliant` vs `needs_review` on the same issue is a
**match with a severity/abstention error**, not a miss — tracked separately so
you can see "found the issue, mis-rated it" distinctly from "didn't find it."

---

## 6. Metric suite

### End-to-end (the headline numbers)
- **Critical recall** = TP_critical / (TP+FN)_critical. *The trust metric.* Floor
  it hard (target ≥ 0.95 to ship). Report with CI.
- **Recall** overall + **per department** + **per severity**. (Denominator =
  labeled findings; state it.)
- **Precision** overall + per department, **after** moving FP-unlabeled out of the
  denominator (adjudicated).
- **Forbidden-flag rate** = forbidden hits / case. Target 0.
- **Citation validity (existence)** — you have this; keep at 1.0 as a CI gate.
- **Citation support (stronger)** — fraction of findings whose cited section
  *actually supports the claim* (LLM/human judged). Existence ≠ relevance.
- **Severity calibration** — confusion matrix over {critical, high, medium, low}
  on matched issues.

### Selective prediction (the `needs_review` axis)
The product's honesty lever is *abstention*. Plot a **risk–coverage curve**:
sort findings by the model's confidence, and as you "auto-assert" more (lower
abstention), how does precision fall? Reward a system that says *"human, check
this"* over one that guesses. Metric: **precision at the coverage level where you
auto-assert vs. defer.**

### Stage-decomposed diagnostics (so you fix the right thing)
- **Extraction accuracy** (Surveyor): occupancy / construction / area (±tolerance)
  / stories / jurisdiction, vs labeled metadata. *Cascading-error source — a
  wrong occupancy poisons every downstream department.*
- **Retrieval recall@k** (Librarian): did it surface the `acceptable_sections`
  for each GT finding? A finding can't be reasoned if the section was never
  retrieved.
- **Reasoning accuracy**: on cases with *correct* extraction + retrieval, the
  conclusion correctness. Isolates the LLM's judgment from upstream noise.

A single end-to-end recall number hides which of these three is bleeding. Compute
all three; the lowest one is your next sprint.

### Operational (track alongside accuracy — they're a unit)
- **Cost / plan** ($ Anthropic + Textract). 95% accuracy at $0.60 ≠ 95% at $40.
- **Latency / plan** (p50/p95).
- **Variance / stability:** run the same plan **N=5** times; measure finding-set
  Jaccard stability. Flaky findings destroy trust even at high mean accuracy. Pin
  temperature/seed where the SDK allows.

### Statistical hygiene
- **Bootstrap 95% CIs** on every rate (resample plans, not findings — findings
  within a plan are correlated).
- **Power:** to detect a 5-pt recall change between versions you need roughly
  hundreds of findings; don't celebrate a 2-case swing.

---

## 7. Harness architecture (extend `benchmarks/`)

```
benchmarks/
  cases/<id>/
    ground_truth.yaml      # extended schema (§4)
    plan_features.yaml     # Tier A synthetic Surveyor output
    plan.pdf               # Tier B/C real PDF  ← WIRE THIS (the big gap)
  runner.py                # modes: --dry | --live-synthetic | --live-pdf
  capture.py   (new)       # log per-stage outputs: extraction, retrieval, dept
  matcher.py   (new)       # tiered matcher (§5) + LLM-judge + adjudication queue
  scorer.py                # metrics (§6) with bootstrap CIs
  report.py    (new)       # per-stratum dashboard, regression vs last run, κ
  manifest.py  (new)       # git SHA + model ids + corpus sha256 + seed per run
  results/<run_id>/        # raw findings, matches, metrics.json, report.md
  adjudication/            # queue of unmatched predictions for human ruling
```

- **`--live-pdf`** runs the *real* Surveyor on `plan.pdf` → full pipeline. This is
  the mode that finally tests extraction. (Today's "plan.pdf not yet wired" gap.)
- **`capture.py`** snapshots `state["plan_data"]`, the Librarian's retrieved
  sections, and each department's raw findings → enables the stage metrics in §6.
- **`manifest.py`** stamps every run so a metric is always tied to *exactly* what
  produced it (model `claude-opus-4-7`, corpus hash, git SHA). Non-negotiable for
  regression tracking.
- Results are append-only history → `report.py` shows **this run vs last** and
  trend lines per metric.

---

## 8. CI + cadence + the ship decision

**Three cadences:**

| When | What runs | Gate |
|---|---|---|
| **Every PR** (CI) | Tier-A dry subset (no API) | citation-validity = 1.00; forbidden = 0; deterministic-engine F1 ≥ 0.95 (your existing `run_eval`) |
| **Pre-release** | Full **dev** set, `--live-pdf` | meets the v1 targets table below, with CIs |
| **Release / model or corpus change** | **Holdout**, `--live-pdf` | the quoted number; ship-gate below |

**Ship gate (formalize your README table with CIs + floors):**

| Metric | v1 (dev) | Ship (holdout, lower CI bound) |
|---|---|---|
| Critical recall | ≥ 0.80 | **≥ 0.95** |
| Citation validity | ≥ 0.95 | 1.00 |
| Citation support | ≥ 0.85 | ≥ 0.95 |
| Precision (overall) | ≥ 0.50 | ≥ 0.75 |
| Forbidden hits | ≤ 2 / case | 0 |
| Extraction accuracy (occupancy/type/area) | ≥ 0.85 | ≥ 0.95 |
| Per-department recall floor | — | no department < 0.70 |

> Rule: if the **lower bound of the 95% CI** on critical recall is below the ship
> target, you do not ship to paying customers — you've not *proven* it's safe,
> regardless of the point estimate.

Treat an accuracy regression like a failing test: it blocks the release.

---

## 9. Pitfalls this design is built to resist

- **Goodhart / overfitting** → sealed holdout; rotate, never tune against it.
- **Incomplete ground truth** → unmatched predictions are *adjudicated*, not
  auto-failed; recall stated as "of labeled findings."
- **Subjectivity inflation/deflation** → κ ceiling; hard vs soft scored apart.
- **Synthetic over-optimism** → Tier B/C real PDFs; clean-plan controls.
- **Distribution mismatch** → strata mirror the real customer plan mix.
- **Nondeterminism** → variance metric; pinned seeds.
- **Cost blindness** → $/plan reported with accuracy.
- **Stage confusion** → extraction/retrieval/reasoning isolated.

---

## 10. Phased rollout (pragmatic for a solo founder)

1. **Week 1 — Plumbing.** Wire `--live-pdf` (real Surveyor on `plan.pdf`),
   `capture.py`, `manifest.py`. Add the extended schema + 1 clean-plan control.
   *Now the harness tests the whole pipe and is reproducible.*
2. **Week 2 — Matching that's fair.** Build `matcher.py` (tiers 1–3 + LLM-judge)
   and the adjudication queue. Re-score your 2 cases honestly.
3. **Weeks 3–4 — Real ground truth.** Get one expediter/firm partner → 20 (plan
   → correction-letter) pairs (Tier C). Label 20–30 more real PDFs with a licensed
   reviewer (Tier B), ≥30% double-labeled for κ. Seal half as holdout.
4. **Week 5 — Metrics + report.** `scorer.py` with bootstrap CIs, stage metrics,
   risk–coverage; `report.py` with per-stratum + regression view.
5. **Ongoing.** CI gate on every PR; pre-release on dev; holdout at releases.
   Watch the lowest stage metric; that's always the next thing to fix.

The first two weeks make your *existing* benchmark honest and end-to-end. Weeks
3–4 are the hard, non-code part — sourcing real labels — and they are the whole
ballgame. No amount of harness polish substitutes for 40 real, expertly-labeled
plans.

---

## 11. What "done" looks like

A single command produces a versioned report that says, with confidence
intervals, per jurisdiction and per department:

> *"On 100 real, expert-labeled plans, PhiCodes catches 96% (CI 92–98%) of
> critical findings and 81% of all findings, at 88% precision, $0.71/plan, with
> zero forbidden flags — measured on a holdout it has never been tuned against."*

That sentence is your sales deck, your legal posture, and your engineering
north-star. Everything in this document exists to make it true and provable.
