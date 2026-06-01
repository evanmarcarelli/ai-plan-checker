# Plan Room AHJ — Architecture

This is the building inspector's tool, not the architect's tool. The
architect-side product (`plan-room-saas`) is a separate codebase that we
keep around as a marketing demo and lead gen for AHJs.

## The thing being built

A multi-tenant SaaS that helps a city's building department triage the
plan-set submittals coming in, so reviewers can spend their time on the
substantive code review instead of the "is this submittal even complete"
question. Secondary value: drafting the formal applicant-facing comment
letters that reviewers spend 30-40% of their time writing.

## Who pays

City and county building departments. Annual contracts in the
$25K–$250K range depending on submittal volume and number of reviewers.
Sales cycle is 6–18 months. Procurement is hard. The buyer is usually a
plan-check supervisor or permit-tech manager with budget signoff from a
deputy director.

## What the AI does and does NOT do

| Layer            | AI's role                                    | Why it works there                                |
|------------------|----------------------------------------------|---------------------------------------------------|
| Scope extraction | LLM pulls structured facts from plan text    | Messy formats, lots of context, schemas help     |
| Completeness     | LLM holistic "is this submittal-ready?"      | Holistic judgment is what humans do here too     |
| Comment drafting | LLM writes formal applicant-facing letters   | Reviewer edits before sending; saves writing time|
| Code math        | **Deterministic** rule engine, never LLM     | LLMs hallucinate numbers; we cannot tolerate that|
| Verdicts         | **Reviewer**, never AI                       | Liability; AHJ authority; trust                   |

Every AI output has a confidence score and is labeled as a draft. Nothing
the AI produces ever appears to the applicant without a reviewer
explicitly accepting it.

## Stack

| Layer        | Choice                       | Why                                       |
|--------------|------------------------------|-------------------------------------------|
| Auth + DB    | Supabase (Postgres + RLS)    | Multi-tenancy, row-level security, free tier handles 100s of users |
| Server logic | Supabase Edge Functions      | No separate backend, Deno isolation, OK for AI workloads |
| LLM primary  | Anthropic Claude             | Best at structured extraction and instruction-following |
| LLM fallback | OpenAI GPT-4o                | Redundancy when Anthropic is down         |
| OCR          | AWS Textract or Google Document AI | Required for scanned PDFs (40%+ of real submittals) |
| Storage      | Supabase Storage             | Private bucket for PDFs with signed URLs  |
| Frontend     | Next.js (planned)            | Multi-page dashboard, real auth flows     |

Note: The current architect-side tool runs entirely in the browser. The
AHJ tool **must** run server-side because (a) PDFs contain protected
information, (b) LLM keys live server-side, (c) multi-user workflows
need durable state, and (d) OCR is server-only.

## The pipeline

```
[ submittal uploaded ]
        |
        v
[ submittal_files row created ]
[ has_text_layer detected ]
        |
        v
( does it have a text layer? )
   /                 \
  no                  yes
   |                   |
   v                   v
[ OCR via Textract ]   |
   |                   |
   +---------+---------+
             |
             v
[ extracted_text written to DB ]
             |
             v
[ POST /process-submittal ]
             |
             v
+------------+-----------------+
|     extractScope (LLM+regex)|   <-- _shared/extract.ts
|      reconciles, surfaces    |
|         ambiguities          |
+------------+-----------------+
             |
             v
+------------+-----------------+
|   evaluateAll (deterministic)|   <-- _shared/evaluate.ts
|   table-driven IBC checks    |
+------------+-----------------+
             |
             v
+------------+-----------------+
|  completenessJudgment (LLM)  |   <-- _shared/triage.ts
|   "is this submittal-ready?" |
+------------+-----------------+
             |
             v
[ triage_runs row written, submittal status -> 'triaged' ]
             |
             v
[ reviewer dashboard surfaces it in the queue, sorted by score ]
             |
             v
[ reviewer clicks finding -> POST /draft-comment ]
             |
             v
[ LLM drafts applicant-facing language ]
             |
             v
[ reviewer accepts/edits/rejects -> review_comments row + feedback row ]
             |
             v
[ comments compiled into letter, sent via separate process ]
```

## Per-agency customization (the moat)

Each agency has:

- `code_year` — what IBC year applies (2018 / 2021 / 2024)
- `rule_overrides` — disable specific rules, change severities
- `custom_rules` — additional AHJ-specific rules (local zoning, ordinances)

This is the moat. UpCodes' codes are generic. PermitFlow's workflows are
generic. Our advantage is that **City of Tacoma's instance knows City of
Tacoma's amendments**, and the longer they use it the more accurate it
becomes (via the feedback loop).

## The feedback loop

When a reviewer accepts, edits, or rejects an AI output:

```
reviewer action -> feedback row (kind, verdict, target, note)
```

We never auto-train on this in v1 — the data accumulates and is reviewed
by us monthly. Once we have ~500 examples per agency, we can use it to:

1. Rank findings by per-agency precision (which rules does this agency
   trust? which produce false positives?)
2. Few-shot LLM prompts with the agency's accepted comment language so
   drafts sound like *this* department's voice
3. Disable rules that consistently produce false positives for an agency
4. Add new rules an agency reviewer manually adds

This data is **strictly per-agency** for privacy. Tacoma's feedback never
trains Houston's system.

## Multi-tenancy enforcement

Every table has `agency_id`. Every RLS policy checks
`auth.uid()` is a member of that agency. Edge functions verify membership
+ role on every request via `_shared/auth.ts::authenticate()`.

A user can belong to multiple agencies (consultants, regional staff).
The active agency is supplied via `X-Agency-Id` header on every API call;
the dashboard's first action after sign-in is "pick your agency."

Roles:
- `admin` — agency settings, member management, all data, billing
- `supervisor` — assigns submittals, sees metrics, can override anyone's review
- `reviewer` — reviews submittals, writes comments
- `intake` — creates submittals, runs triage, cannot finalize reviews

## What's NOT in the schema yet

- Applicant-facing portal (applicants see their own submittals, see
  their comment letter, upload revisions)
- Public records (FOIA-style) read-only access
- Integration with existing permitting systems (Accela, Tyler EnerGov,
  ViewPoint Cloud) — this is a year-2 problem
- Document storage versioning (current schema overwrites; should track
  revisions when applicants resubmit)
- Comment letter generation as a single PDF (currently we just store
  individual comments)

These are deliberate v1 cuts, not oversights.

## Failure modes I'm worried about

**Hallucination in extraction.** An LLM that confidently says "occupancy
is B" when the plan actually says "M" creates downstream chaos. We fight
this with: (a) low temperature, (b) regex cross-check, (c) confidence
scores, (d) ambiguities surfaced to reviewer, (e) the deterministic rule
engine using both values when they disagree and reporting "info" instead
of fail.

**LLM drift.** Anthropic ships a new model; outputs change subtly.
Mitigation: pin model versions in `_shared/llm.ts`, regression-test
against a corpus of past plan sets before upgrading, version the
`pipeline_version` field so we can replay old triages with new pipelines
to compare.

**Review comments that cite the wrong code section.** A reviewer accepts
a draft that says "IBC 1006.3.2" when it should be "1006.3.3"; that
goes out to the applicant; the applicant's lawyer notices. Mitigation:
the reviewer is liable, not us — comments are explicitly drafts the
reviewer must accept. The UI must make this clear.

**Cost runaway.** A bug in the prompt or a malicious input generates a
giant LLM bill. Mitigation: hard token limits in the LLM client, daily
cost alerts, per-agency monthly cap, the `llm_usage` table for
observability.

## Pricing model (as of v1)

| Tier        | Annual price | Submittals/yr | Reviewers | Best for                |
|-------------|--------------|----------------|-----------|------------------------|
| Pilot       | $5K-15K      | up to 500      | 3         | First contract, 6-month term |
| Small city  | $25K-50K     | up to 2,000    | 5         | <100K population       |
| Mid city    | $50K-100K    | up to 5,000    | 10        | 100-500K population    |
| Large city  | $100K-250K   | up to 20,000   | 25        | 500K-2M population     |
| Enterprise  | Custom       | unlimited      | unlimited | Counties, large cities |

The marginal cost per submittal in OCR + LLM is ~$0.50-2.00. Even at
$25K/year for 2000 submittals that's $50K of margin per contract per
year. The math works once you have a few customers. Year 1 you're
mostly losing money on sales effort and engineering, not unit economics.

## Jurisdiction-aware retrieval pipeline

The **Surveyor** (`_shared/surveyor.ts`) is a deterministic pre-step that runs once per
submittal before the Researcher loop. It answers the question: *"Which code sources apply
to THIS specific job?"*

```
[ process-submittal ]
        |
        v
[ surveyJurisdiction(jurisdictionKey, projectAddress) ]   ← _shared/surveyor.ts
        |
        |-- MUNICODE_CA_REGISTRY lookup (LA, SD, SF, San Jose, ...)
        |-- ECODE360_REGISTRY lookup (NJ, NY suburbs, CT, MD, VA, PA)
        |-- CalFire FHSZ GIS lookup (CA only, async) ← _shared/wui.ts
        |
        v
[ JurisdictionProfile { sources: [...], wuiZone, ibcYear } ]
        |
        +-------> scope.wui_zone (attached before rule eval)
        |
        v
[ runTriage() with jurisdictionProfile in research options ]
        |
        v
[ research() gets profile.sources as ordered fetch hints ]
```

**Source priority within the Researcher:**
1. Municipality code (Municode / eCode360 / amlegal / direct .gov)
2. State code (CBC for CA, NYSBC for NY, NJ UCC, etc.)
3. IBC baseline (cite section + summary only — see `docs/ICC_LICENSING.md`)

A San Jose plan never gets reviewed against Pasadena's code. A Hoboken NJ
submittal searches `site:ecode360.com/JE0471` before falling back to generic web.

## CalFire FHSZ WUI overlay

For CA projects where a `project_address` is on the submittal:
- Address is geocoded via the free US Census Geocoder (no API key)
- Lat/lng is queried against CalFire's public ArcGIS REST service (SRA layer 0 + LRA layer 1)
- Result is cached in `wui_zone_cache` (TTL 1 year) and on `submittals.wui_zone`
- Three new deterministic rules activate when the project is in a High or Very High FHSZ:
  - `FIRE-WUI-7A` — CBC Chapter 7A materials (critical)
  - `FIRE-WUI-VENT` — ember-resistant vents CBC 708A (major)
  - `FIRE-WUI-DECK` — ignition-resistant decks CBC 709A (major)

These rules produce `info` for non-CA jobs so they never pollute other jurisdictions.

## Code source registries

| Registry | File | Covers |
|----------|------|--------|
| `MUNICODE_CA_REGISTRY` | `_shared/scrapers/municode.ts` | LA, San Diego, SF, San Jose, Fresno, Sacramento |
| `ECODE360_REGISTRY` | `_shared/scrapers/ecode360.ts` | NJ (Hoboken, Princeton, Montclair, Jersey City, Newark), NY suburbs, CT, MD, VA, PA |
| `JURISDICTION_REGISTRY` | `_shared/surveyor.ts` | All of the above + WA, TX, FL, IL + state-level fallbacks |

To add a new jurisdiction: add an entry to the appropriate registry, add the
jurisdiction key to `JURISDICTION_REGISTRY`, and it flows through automatically.

## ICC licensing

IBC text is ICC copyrighted. See `docs/ICC_LICENSING.md` for the decision.
Short version: cite section numbers + summarize in v1; UpCodes API for verbatim
text in v1.5 after first 3 paid contracts.

## Where this codebase ends and the next phase begins

Currently shipped:
- Multi-tenant schema with RLS
- LLM client with structured outputs and cost tracking
- Hybrid (LLM + regex) scope extraction with reconciliation
- Deterministic rule evaluator with confidence propagation
- Triage orchestrator with LLM completeness judgment
- `process-submittal` edge function
- `draft-comment` edge function

Still needed before paying customers:
- **Reviewer dashboard** — the queue UI where reviewers spend their day
- **Submittal detail page** — PDF viewer + findings + comment composer
- **Settings UI** — agency settings, member management, custom rules editor
- **Applicant intake** — receive submittals from applicants directly (or
  via API integration with existing permitting systems)
- **Comment letter generation** — assemble accepted comments into a
  formal PDF letter
- **OCR integration** — wire up Textract for scanned submittals
- **Analytics** — supervisor view: turnaround time, % bounced at intake,
  reviewer productivity, AI accuracy by rule
- **SOC 2 readiness work** — required for larger cities (~$20-40K consulting)
