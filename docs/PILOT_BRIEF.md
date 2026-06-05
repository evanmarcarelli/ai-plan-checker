# Plan Room AHJ (up2code) — 90% Broad-Scope Pilot Brief

You are working on **Plan Room AHJ** (also called up2code internally), an AI
permit-review SaaS targeting LADBS submittals. The product is a Supabase +
Next.js stack: Edge Functions in `supabase/functions/`, Next.js dashboard in
`web/`, migrations in `supabase/migrations/`. The eval harness lives in
`scripts/eval/`.

## Locked decision — do not re-litigate

**Target: 90% accuracy on broad scope. Not 99% on narrow scope.**

Rationale: 99% requires 5,000+ ground-truth cases, vector PDF dimension
analysis, N-of-5 critic ensembles, and 8–12 months — by which time the
company has no customers. 90% is what a junior plan checker hits on first
pass, it's commercially defensible, and it unlocks ~55–65% of LA
submittal volume across 3–5 city pilots instead of 10–15% of one city.

If a proposal would push toward 99% at the cost of timeline or scope —
**reject it inline, do not entertain it.** Examples of 99%-trap proposals
to refuse: dual-extraction with regex + Sonnet + Opus voting, building a
vector PDF dimension analyzer in-house, confidence thresholds above 0.80,
adding a second critic model, expanding the eval set past 500 cases
before a pilot ships.

## In-pilot scope (the only archetypes triage runs on)

| Archetype slug | Definition |
|---|---|
| `la_sfr_typ_v_residential` | R-3 single-family, Type V-A/V-B/IV, ≤ 3 stories, ≤ 7,500 sf per story, sprinklered or non-sprinklered |
| `la_sfr_addition` | R-3 addition or remodel ≥ 200 sf, same constraints as above |
| `la_ti_commercial` | Tenant improvement, Group B/M/F-1/S-1, any size up to existing shell, no envelope change |
| `la_small_commercial_new` | New construction, Group B/M/F-1, ≤ 10,000 sf per story, ≤ 2 stories, ≤ 35 ft height |
| `la_low_rise_multifamily` | R-2, ≤ 6 units, single building, ≤ 3 stories, sprinklered |

Edge archetypes (run triage but flag for extra reviewer attention):
- `la_assembly_small` — A-2 / A-3 with OL < 300
- `la_school_small` — E occupancy, single building

## Out-of-pilot scope (reject at intake, do not run rule engine)

Always rejected — return `out_of_pilot_scope` with a specific reason:
- Hillside / BMO / BHO zoning (geometry rules we don't have)
- HPOZ (Historic Preservation Overlay Zone) — requires architectural judgment
- CA Coastal Zone (separate regulatory body)
- High-rise: height > 75 ft or stories ≥ 5
- I-2 hospital, H hazardous, I-3 detention
- Mixed-use new construction (R over M, etc.)
- FEMA flood zone AE / VE
- Anything the archetype classifier returns as `unclassified`

The archetype gate already exists in
`supabase/functions/_shared/archetype.ts` and runs in
`supabase/functions/_shared/triage.ts` step 1c. Extend that file when
adding archetypes — do not bypass the gate.

## What 90% means, measurably

- **Per-finding precision ≥ 90%** on the eval set: when the system says
  "fail," the ground truth agrees ≥ 90% of the time.
- **Per-finding recall ≥ 85%** on the eval set: the system catches
  ≥ 85% of real issues. Recall < precision is intentional — false
  negatives are more forgivable to reviewers than false positives.
- **Out-of-scope rejection precision ≥ 95%**: when the gate says
  "reject," it's right 95% of the time.
- Measured on the eval harness at `scripts/eval/run-eval.ts`.

## What's already shipped (don't rebuild)

- Multi-tenant Supabase schema with RLS (migrations 0001–0007)
- LLM client with cost tracking, structured output, tool-use loop
  (`_shared/llm.ts`)
- Hybrid LLM + regex scope extraction with reconciliation
  (`_shared/extract.ts`)
- Deterministic checker primitives + unit tests
  (`_shared/checkers.ts`, `checkers.test.ts`)
- Rule evaluator (`_shared/evaluate.ts`)
- Jurisdiction Surveyor + property profile resolver
  (`_shared/surveyor.ts`, `_shared/property.ts`)
- Vector code corpus (CBC, CRC, LA amendments) with semantic search
  (migration 0004, `_shared/corpus.ts`)
- Researcher agent with citation verification (`_shared/research.ts`)
- LABC amendment diff lookup (`_shared/amendments.ts`)
- Archetype classifier + gate (`_shared/archetype.ts`, migration 0007)
- Citation gate (uncited fails auto-downgrade to warn,
  `triage.ts` step 4c)
- Adversarial Opus critic (`_shared/critic.ts`, `triage.ts` step 4d)
- Eval harness + 7 fixtures (`scripts/eval/`)

## Ordered work queue to reach 90% (do in this order)

**Month 1 — front door**
1. PDF upload + signed URL flow into `submittals` Storage bucket
2. Text extraction via **Vertex AI Gemini Pro** (NOT free AI Studio — PII)
3. Sheet markers inlined in `extracted_text` (`=== SHEET A-0.1 · CODE
   ANALYSIS · pp.3 ===\n...`) so existing `extract.ts` benefits without
   changes
4. Per-sheet metadata rows in new `submittal_sheets` table (no
   downstream consumer yet; will become Textract's home in Month 3)

**Month 2 — eval set + reviewer dashboard**
5. Recruit 1 friendly LADBS partner; collect 100 real submittals with
   correction lists as ground truth. Convert to fixtures.
6. Wire reviewer dashboard: PDF viewer + inline citation + accept /
   edit / reject buttons. The dashboard exists at
   `web/src/app/(dashboard)/queue/[id]/page.tsx` but is half-built.
7. Confidence gate at 0.75 — findings below threshold show as
   "needs verification" not "fail"

**Month 3 — Textract for the 40% scanned PDFs**
8. Add Textract `DETECT_DOCUMENT_TEXT` (not `TABLES` — too expensive for
   v1) as the OCR path for raster PDFs. Gemini stays for digital.
9. Per-word OCR confidence scores attached to scope inputs; rules
   degrade gracefully when input confidence < 0.7

**Month 4 — pilot prep**
10. Grow eval set to 300 cases (target: 50+ per in-scope archetype)
11. Per-rule F1 regression gate in CI (Δ ≤ 2 pts to ship)
12. Adversarial red-team set: 30 hand-curated hardest cases that must
    pass before any model/prompt change

## Hard NOs (do not propose these in this phase)

- N-of-5 critic ensemble — 1 critic is enough for 90%
- Vector PDF dimension analyzer — license-vs-build comes later
- Eval set > 500 cases — diminishing returns vs. shipping
- Confidence gate > 0.80 — defers too many findings, kills usability
- Per-rule F1 gate stricter than Δ ≤ 2 pts — slows iteration
- Adding a Title 24 prescriptive energy compliance checker — out of scope
- Reviewer dashboard rewrites in a different framework — Next.js stays
- Switching off Supabase — too much wiring; would burn 3 months

## Forcing functions (gates that prevent drift)

Every code change must pass:
1. `deno test supabase/functions/_shared/checkers.test.ts` — unit tests green
2. `deno run scripts/eval/run-eval.ts` — eval F1 must not drop > 2 pts
   on any in-scope archetype vs. last labeled run
3. New archetype additions require a fixture covering it before the
   gate is opened
4. PR description states which of the 12 ordered work items it advances

## Style / decision rules for code work

- Match existing style: TypeScript, no semicolon-skipping, Deno-style
  imports in `supabase/functions/`, npm-style in `web/`
- Pure functions for all math; LLM only for extraction and judgment
- Every "fail" finding must carry a citation OR auto-downgrade to "warn"
  (this rule is already enforced in `triage.ts` 4c)
- New rules added to `BASELINE_RULES` must declare `requires_citation`
- New rules require a unit test in `checkers.test.ts` if they involve math
- No new dependencies without justification; current stack is sufficient

## Pricing-narrative this enables

Target pricing for the broad-scope 90% pilot:
- Pilot tier: $15K–25K / year per city, up to 1,000 submittals
- Sales pitch: "Catches 85%+ of issues on first pass; reviewer verifies
  every flag. Cuts correction-letter writing time by 40%."
- Do NOT promise: "approves submittals," "replaces a plan checker,"
  "guarantees code compliance."

## When in doubt

The question to ask: **"Does this advance the Month 1–4 work queue,
or does it pattern-match to the 99% trap?"** If the latter, push back
and propose the smaller version that fits the 90% target.
