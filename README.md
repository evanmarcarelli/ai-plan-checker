# Plan Room AHJ

Multi-tenant SaaS for city building departments. Triages incoming plan
submittals, drafts the formal applicant-facing comment letters, and
gives reviewer dashboards a "completeness score" so they know which
submittals are worth their time.

This is the **AHJ-side product** — sold to cities, not architects. The
architect-facing tool (`plan-room-saas`, separate repo) becomes our
demo and lead-gen funnel.

## What this delivery contains (backend)

```
plan-room-ahj/
├── supabase/
│   ├── migrations/
│   │   └── 0001_init.sql            multi-tenant schema, RLS, audit, llm cost log
│   └── functions/
│       ├── _shared/
│       │   ├── auth.ts              authenticate() + audit() helpers
│       │   ├── llm.ts               LLM client (Claude primary, GPT fallback)
│       │   ├── rules.ts             code knowledge base + agency override merger
│       │   ├── extract.ts           hybrid LLM+regex scope extraction
│       │   ├── evaluate.ts          deterministic rule evaluator
│       │   └── triage.ts            pipeline orchestrator
│       ├── process-submittal/       triggers full pipeline on a submittal
│       └── draft-comment/           drafts applicant-facing comment text
├── docs/
│   ├── ARCHITECTURE.md              shape of the system, decisions explained
│   └── SETUP.md                     step-by-step deployment guide
└── README.md
```

**Not yet built:** reviewer dashboard, submittal-detail page, OCR
integration, applicant intake portal, comment-letter PDF assembly.
That's the next conversation.

## Pipeline diagram

```
PDF arrives → text extracted → process-submittal triggered →
  extractScope (LLM + regex, reconciled) →
  evaluateAll (deterministic rules over scope) →
  completenessJudgment (LLM holistic call) →
  triage_runs row written →
  reviewer queue surfaces it sorted by completeness score
                    ↓
  reviewer clicks finding → draft-comment endpoint → LLM drafts
  formal applicant-facing language → reviewer edits/accepts → saved
  to review_comments → feedback row records the verdict (training signal)
```

## Setup

See **[docs/SETUP.md](docs/SETUP.md)**.

1. Create Supabase project, paste schema, configure auth + storage
2. Add yourself as agency admin in the seeded `demo-city` agency
3. Set `ANTHROPIC_API_KEY` (and `OPENAI_API_KEY` if using fallback)
4. `supabase functions deploy process-submittal draft-comment`
5. Run the smoke test in the setup guide

About 60-90 minutes the first time.

## Architecture decisions

See **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)** for the longer
discussion. The short version:

- **Server-side** — unlike the architect tool, AHJ data is sensitive
  and the workflow is multi-user. Everything that matters runs in
  Edge Functions.
- **LLM for language and extraction, deterministic for math.** LLMs
  hallucinate numbers; we cannot tolerate that on a code-compliance
  question. Every numeric / table-driven check is plain TypeScript.
- **Multi-tenancy from day one.** Every table has `agency_id`, every
  RLS policy enforces membership, every API call resolves the active
  agency before doing anything.
- **Append-only audit log + LLM cost log.** Auditable for FOIA
  requests; observable so we can see our own LLM spend.
- **Per-agency rule customization is the moat.** Tacoma's instance
  knows Tacoma's amendments; UpCodes is generic. The longer they use
  it, the better it gets, the harder to switch.

## What good progress looks like for the next quarter

- [ ] Reviewer dashboard (Next.js): queue view, submittal detail, comment composer
- [ ] OCR integration for scanned PDFs (AWS Textract)
- [ ] Comment-letter PDF assembly
- [ ] Settings UI for agency admins (members, custom rules, code year)
- [ ] One paid pilot signed ($5-25K, 6 month term)

## Honest limits

The auditor's accuracy is bounded by the text layer. On scanned plan
sets, we need OCR. On hand-marked-up PDFs, we miss callouts. On
geometry-based questions (actual measured travel distance, actual
exit separation), we cannot compete with a human reviewer's eyes on
the drawings. The product is a **triage aid**, not a substitute for
the licensed reviewer's judgment. Marketing copy must reflect this.

## License

(Decide later. For pre-revenue, MIT or Apache 2 with an explicit "not
for resale" rider is reasonable.)
