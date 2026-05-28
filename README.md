# Up2Code — AI Plan Checker

> Multi-agent AI system for automated building code compliance verification.
> Upload a PDF plan set → 12 specialized agents review it in parallel against
> jurisdiction-specific code text → get a structured compliance report with
> verified citations.

Live demo: [ai-plan-checker.vercel.app](https://ai-plan-checker.vercel.app/#demo)

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                       Next.js Frontend                          │
│  Upload → Live agent timeline → Triage report → PDF / share     │
│             Supabase auth · Stripe pay-per-credit               │
└─────────────────────────────────────────┬───────────────────────┘
                                          │ HTTP / WebSocket
┌─────────────────────────────────────────▼───────────────────────┐
│                         FastAPI Backend                         │
│                                                                 │
│   ┌────────────┐    ┌────────────┐    ┌──────────────────┐      │
│   │  Surveyor  │ →  │  Librarian │ →  │  Department fan- │      │
│   │            │    │            │    │  out (10 agents) │      │
│   │ Resolves   │    │ Pulls code │    │                  │      │
│   │ AHJ + GIS  │    │ chunks for │    │ Building & Safety│      │
│   │ overlays   │    │ jurisdic-  │    │ Fire             │      │
│   │ (WUI,      │    │ tion via   │    │ Electrical       │      │
│   │  FHSZ,     │    │ BM25       │    │ Plumbing         │      │
│   │  flood)    │    │ retriever  │    │ Mechanical       │      │
│   │            │    │            │    │ Accessibility    │      │
│   └────────────┘    └────────────┘    │ Energy/CALGreen  │      │
│                                       │ Planning/Zoning  │      │
│                                       │ Public Works     │      │
│                                       │ Environmental    │      │
│                                       └────────┬─────────┘      │
│                                                │                │
│                                       ┌────────▼─────────┐      │
│                                       │     Auditor      │      │
│                                       │ Synthesizes      │      │
│                                       │ findings,        │      │
│                                       │ scores, drafts   │      │
│                                       │ correction notice│      │
│                                       └──────────────────┘      │
│                                                                 │
│  PDF extraction · BM25 retrieval over JSONL corpus              │
│  Anthropic Claude Opus 4.7 primary · GPT-4o fallback            │
│  Export: PDF (ReportLab) · CSV · public shareable read-only link│
└─────────────────────────────────────────────────────────────────┘
```

---

## Agent workflow

### Surveyor
- Extracts text from every sheet (PyMuPDF + pdfplumber), focused on title block + cover sheet
- Resolves jurisdiction (city → county → state) from address or stamped title block
- Pulls property overlays: CalFire FHSZ wildfire zone, FEMA flood, CA Coastal Zone
- Returns a structured project scope: occupancy, construction type, area, height, stories, sprinklered, mixed-occupancy

### Librarian
- BM25 retrieval over a pre-indexed code corpus (JSONL) filtered by `jurisdictions` scope (`*`, state, county, `CA:<city>`)
- Returns the top-k applicable rule snippets, each with a stable source URL
- Backed by 7 base-code corpora + a 15-jurisdiction California municipal ingest pipeline (American Legal Publishing scraper)

### Department reviewers (run in parallel)
Ten domain agents, each scoped to its own building-department lens. Each issues `pass / fail / warn / info` findings against the retrieved code chunks, with severity and verified citation.

| Department | Lens |
|---|---|
| Building & Safety | Occupancy declaration, construction type, EERO, structural notes |
| Fire | Sprinklers (NFPA 13), alarm (NFPA 72), Ch. 7A WUI material schedules |
| Electrical | NEC service rating, GFCI, panel schedule |
| Plumbing | IPC fixture counts, water heater venting |
| Mechanical | ASHRAE 62.1 ventilation, IMC duct routing |
| Accessibility | CBC 11A/11B + ADA 2010 routes, ramps, parking |
| Energy & CALGreen | Title 24 Part 6 + Part 11, prescriptive PV, envelope |
| Planning & Zoning | Setbacks, lot coverage, FAR, ADU rules |
| Public Works | Right-of-way, encroachment, driveway approach |
| Environmental | PRC §4291 defensible space, stormwater, CEQA notes |

### Auditor
- Merges all department findings into a single ordered list
- Computes a 0–100 completeness score + letter grade
- Drafts a 1–2 sentence assessment and a ready-to-send correction notice
- Surfaces the top-N reviewer questions back to the applicant

---

## Code corpus

7 base-code corpora ship in `backend/app/code_library/corpus/` as JSONL chunks, retrievable by jurisdiction scope:

| Code | Version | Scope |
|---|---|---|
| IBC — International Building Code | 2021 | `*` |
| IFC — International Fire Code | 2021 | `*` |
| IPC / IMC — Plumbing & Mechanical | 2021 | `*` |
| NEC — National Electrical Code | 2023 | `*` |
| ADA Accessibility Guidelines | 2010 | `*` |
| Title 24 (CA Energy + CALGreen) | 2022 | `CA` |
| Zoning + Public Works baseline | — | `*` |

California municipal ingest pipeline (`backend/app/code_library/ingest/`) currently targets 15 jurisdictions via American Legal Publishing:

> Pasadena · Long Beach · Glendale · Burbank · Santa Monica · Beverly Hills · Oakland · San Jose · Sacramento · Fremont · Anaheim · Irvine · Bakersfield · Riverside · San Bernardino

Run `python -m app.code_library.ingest <slug>` to pull a jurisdiction's municipal code into the corpus.

---

## Quick start

### Prerequisites
- Python 3.11+
- Node.js 20+
- Docker + Docker Compose *(optional, recommended for full-stack local dev)*
- An Anthropic API key (Claude Opus 4.7)

### Option A — Docker Compose

```bash
cp backend/.env.example backend/.env
# fill in ANTHROPIC_API_KEY + SUPABASE_* + STRIPE_* in backend/.env

docker-compose up -d
open http://localhost:3000
```

### Option B — Local dev

**Backend**
```bash
cd backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # set ANTHROPIC_API_KEY + Supabase keys
uvicorn app.main:app --reload --port 8000
```

**Frontend**
```bash
cd frontend
npm install
cp .env.local.example .env.local
npm run dev
```

---

## Environment

### Backend (`.env`)

| Variable | Required | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | Yes | Claude Opus 4.7 — primary LLM |
| `ANTHROPIC_MODEL` | No | Defaults to `claude-opus-4-7` |
| `OPENAI_API_KEY` | No | GPT-4o fallback if Anthropic times out |
| `SUPABASE_URL` | Yes | Supabase project URL |
| `SUPABASE_ANON_KEY` | Yes | Public anon key |
| `SUPABASE_SERVICE_ROLE_KEY` | Yes | Service role key (server-only) |
| `SUPABASE_JWT_SECRET` | Yes | JWT signing secret for API auth |
| `STRIPE_SECRET_KEY` | Yes | Billing — pay-per-credit checkout |
| `STRIPE_WEBHOOK_SECRET` | Yes | Stripe webhook signature validation |
| `STRIPE_PRICE_PACK_{1,5,25,100}` | Yes | Stripe price IDs for the credit packs |
| `SENTRY_DSN` | No | Error tracking |

### Frontend (`.env.local`)

| Variable | Default | Description |
|---|---|---|
| `NEXT_PUBLIC_API_URL` | `http://localhost:8000` | Backend API |
| `NEXT_PUBLIC_WS_URL` | `ws://localhost:8000` | WebSocket endpoint for live agent logs |
| `NEXT_PUBLIC_SUPABASE_URL` | — | Supabase project URL |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | — | Supabase anon key |
| `NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY` | — | Stripe publishable key |

---

## API

```
POST   /api/v1/upload                 Upload PDF → returns job_id
GET    /api/v1/jobs/{id}              Job status + final report
GET    /api/v1/jobs/{id}/logs         All agent log entries
GET    /api/v1/jobs/{id}/export/pdf   Download PDF report
GET    /api/v1/jobs/{id}/export/csv   Download CSV report
POST   /api/v1/jobs/{id}/share        Create a public read-only share link
DELETE /api/v1/jobs/{id}              Delete job + uploads
GET    /api/v1/jobs                   Recent jobs for the authed user

WS     /api/v1/ws/{id}                Real-time per-agent log stream
GET    /health                        Health check
GET    /docs                          Swagger UI
```

---

## Pricing

Pay-per-use credits. One credit = one full plan-set review.

| Pack | Credits | Price | Per-check |
|---|---|---|---|
| Try one | 1 | $60 | $60.00 |
| Single project | 5 | $179 | $35.80 |
| Firm pack | 25 | $772 | $30.88 |
| Annual / enterprise | 100 | $2,999 | $29.99 |

---

## Testing

```bash
cd backend
pytest tests/ -v
pytest tests/ -v --cov=app --cov-report=html
pytest tests/test_agents.py::TestAuditorAgent -v
```

---

## Extending

### Add a new department reviewer
Add a class to `backend/app/agents/departments.py` extending `DepartmentReviewer`, then append it to `ALL_DEPARTMENTS`. The workflow fans out across the list automatically.

### Add a new code source
Add an entry to `backend/app/code_library/ingest/jurisdictions.yaml`. For American Legal Publishing sources, set `source_id` to the amlegal slug (e.g. `pasadena_ca`). Run `python -m app.code_library.ingest <source_id>` to scrape + chunk.

### Switch LLM provider
The `app.agents.base.BaseAgent` resolves provider via env (`ANTHROPIC_API_KEY` preferred, falls back to OpenAI). Override `BaseAgent._call_llm` to add a new provider.

---

## Production deployment

- Frontend: Vercel (auto-deploys from `main`)
- Backend: Render (Dockerfile in `backend/`), or any Docker host
- Vector store: Supabase Postgres (pgvector) — see `backend/migrations/`
- Job queue: in-process today; Celery + Redis when scaling past single-node

---

## License

MIT — see `LICENSE`.
