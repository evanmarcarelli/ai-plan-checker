# Plan Room AHJ — Backend Setup

This guide gets the **server side** of Plan Room AHJ running. The
reviewer dashboard frontend is a separate piece that gets built on top
of these APIs.

You will need accounts at:

- **Supabase** — database + auth + edge functions
- **Anthropic** — primary LLM (sign up at console.anthropic.com)
- **OpenAI** — fallback LLM (optional but recommended)
- **AWS or Google Cloud** — for OCR (only needed once you handle scanned PDFs)

Estimated time: 60-90 minutes for Supabase + LLM setup. Add another
hour for AWS Textract once you need OCR.

## 1. Apply the database schema

Create a new Supabase project. Settings → Database → connection string,
or just use the SQL Editor in the dashboard.

Paste the contents of `supabase/migrations/0001_init.sql` and run it.
You should see:

- 10 tables created
- 6 enum types created
- 18 RLS policies created
- 1 demo agency seeded (`demo-city`)

**Then run `supabase/migrations/0002_research_cache.sql`** to add the
live-research citation cache:

- `code_citations` — verified code text per (jurisdiction, code_ref), 90-day expiry
- `research_runs` — per-session log of agentic research (cost, iterations, outcome)
- Adds `jurisdiction_key` column to `agencies`

Verify:

```sql
select count(*) from public.agencies;        -- 1
select count(*) from public.agency_members;  -- 0
select count(*) from public.code_citations;  -- 0
select count(*) from public.research_runs;   -- 0
```

## 2. Configure auth + storage

**Authentication → Providers → Email**: enable. For development, turn
off "Confirm email" so you can sign up freely.

**Storage → Create bucket**:
- Name: `submittals`
- Public: **off** (private bucket)
- File size limit: 200 MB (typical commercial plan set is 50-150 MB)

Add a storage policy so agency members can read their agency's files:

```sql
create policy "submittals: agency-scoped read"
  on storage.objects for select
  using (
    bucket_id = 'submittals'
    and (storage.foldername(name))[1] in (
      select agency_id::text from public.agency_members
      where user_id = auth.uid()
    )
  );

create policy "submittals: staff write"
  on storage.objects for insert
  with check (
    bucket_id = 'submittals'
    and (storage.foldername(name))[1] in (
      select agency_id::text from public.agency_members
      where user_id = auth.uid()
        and role in ('admin','supervisor','intake','reviewer')
    )
  );
```

(File path convention: `<agency_id>/<submittal_id>/<filename>.pdf`)

## 3. Create your first agency admin

Sign up via the Supabase Auth dashboard with your email/password.
Then add yourself as an admin of the demo agency:

```sql
-- Find your auth.users.id (or use the dashboard's user list)
insert into public.agency_members (agency_id, user_id, role, display_name)
select id, '<YOUR-AUTH-USER-ID>', 'admin', 'Founder'
from public.agencies where slug = 'demo-city';
```

## 4. Set the edge function secrets

You need the Supabase CLI:

```bash
brew install supabase/tap/supabase   # macOS
# or follow https://supabase.com/docs/guides/cli for other OS
supabase login
supabase link --project-ref <YOUR-PROJECT-REF>
```

Set the LLM API keys as function secrets:

```bash
supabase secrets set \
  ANTHROPIC_API_KEY="sk-ant-..." \
  OPENAI_API_KEY="sk-..." \
  BRAVE_API_KEY="BSAxxxxx..." \
  SERPER_API_KEY="optional-fallback"
```

- **`ANTHROPIC_API_KEY`** — primary LLM. Required.
- **`OPENAI_API_KEY`** — fallback LLM. Optional but recommended.
- **`BRAVE_API_KEY`** — used by the Researcher agent for live web search
  against authoritative code sources. Sign up at api.search.brave.com
  (free tier covers ~2K queries/month). Required for live citations;
  pipeline gracefully degrades if missing.
- **`SERPER_API_KEY`** — optional Google-search fallback if Brave is down.

`SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` are auto-populated.

## 5. Deploy the edge functions

```bash
supabase functions deploy process-submittal
supabase functions deploy draft-comment
supabase functions deploy research-rule
```

The three functions:

- `process-submittal` — full triage pipeline. Optionally invokes the
  Researcher agent to attach verified citations to failing findings.
- `draft-comment` — LLM drafts the formal applicant-facing comment text.
  When a citation is attached to the finding, the LLM is given the
  verified code text to quote from instead of relying on memory.
- `research-rule` — direct endpoint to invoke the Researcher for a
  specific (jurisdiction, code_ref) tuple. Useful for warming the
  citation cache or for reviewer-initiated lookups.

## 6. Smoke test the pipeline

Curl test (replace `<JWT>` with your sign-in token from the Supabase
dashboard, and `<AGENCY-ID>` with the demo-city agency id):

```bash
# Create a test submittal
curl https://<PROJECT-REF>.supabase.co/rest/v1/submittals \
  -X POST \
  -H "apikey: <ANON-KEY>" \
  -H "Authorization: Bearer <JWT>" \
  -H "Content-Type: application/json" \
  -H "Prefer: return=representation" \
  -d '{
    "agency_id": "<AGENCY-ID>",
    "project_name": "Test Smoke Project",
    "project_address": "123 Test St, Demo City, WA",
    "applicant_name": "Test Applicant",
    "project_type": "commercial_new"
  }'
# -> note the returned submittal id

# Run triage on it (passing plan_text directly)
curl https://<PROJECT-REF>.supabase.co/functions/v1/process-submittal \
  -X POST \
  -H "Authorization: Bearer <JWT>" \
  -H "X-Agency-Id: <AGENCY-ID>" \
  -H "Content-Type: application/json" \
  -d '{
    "submittal_id": "<SUBMITTAL-ID>",
    "plan_text": "OCCUPANCY GROUP B (BUSINESS)\nCONSTRUCTION TYPE: II-B\nTOTAL AREA: 8400 SF\nBUILDING HEIGHT: 24 FT\nNUMBER OF STORIES: 2\nFULLY SPRINKLERED: YES (NFPA 13)\nOCCUPANT LOAD: 60\nTRAVEL DISTANCE: 180 FT\nEXIT 1: FRONT ENTRY 36\"\nEXIT 2: REAR EGRESS 36\""
  }'
```

You should get back something like:

```json
{
  "triage_run_id": "...",
  "completeness": {
    "score": 87.5,
    "grade": "B",
    "headline": "Submittal is largely complete; minor follow-up needed.",
    "missing_items": ["..."],
    "assessment": "..."
  },
  "stats": { "total": 16, "pass": 13, "fail": 2, "warn": 1, "info": 0 },
  "duration_ms": 4200,
  "llm_cost_usd": 0.018
}
```

If you see `"used_llm": true` in the saved triage_run report and a
non-zero `llm_cost_usd`, the LLM pipeline is wired up correctly.

## 7. Verify the LLM cost log

```sql
select purpose, model, input_tokens, output_tokens, cost_usd, latency_ms
from llm_usage
order by created_at desc limit 10;
```

You should see rows for `extract_scope` and `completeness_judgment`,
each with non-zero token counts and a sub-cent cost.

## 8. Test the comment drafter

Create a review on the smoke-test submittal, then:

```bash
curl https://<PROJECT-REF>.supabase.co/functions/v1/draft-comment \
  -X POST \
  -H "Authorization: Bearer <JWT>" \
  -H "X-Agency-Id: <AGENCY-ID>" \
  -H "Content-Type: application/json" \
  -d '{
    "review_id": "<REVIEW-ID>",
    "reviewer_note": "egress capacity insufficient for stated occupant load",
    "code_ref": "IBC 1005.3.2",
    "severity": "correction_required"
  }'
```

You should get back a JSON object with a `body` field containing
formal applicant-facing comment language, ready for the reviewer to
edit and accept.

## What to do next

1. Build the reviewer dashboard (Next.js, separate codebase or `/dashboard` app)
2. Wire up file upload to Supabase Storage with browser-side text extraction
3. Add the OCR endpoint for scanned PDFs (AWS Textract integration)
4. Run a real plan set through end-to-end
5. Get a friendly mid-size city to do a 30-day pilot

## Cost expectations during development

- Supabase: free tier covers everything until you have real users
- Anthropic: budget $50-100/month during active development
- OpenAI: $20-30/month if used as fallback
- AWS Textract: pay-per-use, ~$1.50 per 1000 pages

Operating cost per submittal (once production):
- LLM calls (extract + completeness + 2-3 comments): $0.10-$0.50
- OCR (if scanned, 100 pages): ~$0.15
- Storage: negligible
- Total: **$0.25-$0.65 per submittal**

At $50K/year for a 2000-submittal city, your COGS is ~$1300/year, so
gross margin is ~97%. The cost is sales, not delivery.

## Troubleshooting

- **`401 invalid token`** — your JWT expired. Get a fresh one from the
  Supabase dashboard or sign in again via your front-end.
- **`403 not a member of this agency`** — you forgot to insert yourself
  into `agency_members` (step 3).
- **`process-submittal` returns `triage failed`** — check function logs
  in the Supabase dashboard. Most common cause: `ANTHROPIC_API_KEY`
  not set (`supabase secrets list` to verify).
- **LLM returns garbage / non-JSON** — check the prompt in
  `_shared/triage.ts`. The schema-validation in `_shared/llm.ts` will
  retry up to 2x; persistent failures land in the function logs.
- **Cost is way higher than expected** — check `llm_usage` for the
  outlier rows. Most common cause: a large `plan_text` payload that
  blew past the 30K character truncation in `extract.ts`.
