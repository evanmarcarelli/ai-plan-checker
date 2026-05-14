# AI Plan Checker v2.0

> Multi-agent AI system for automated building code compliance verification.

Upload a PDF plan set → three specialized agents analyze it → get a detailed compliance report.

---

## Architecture

```
┌─────────────────────────────────────────────┐
│              Next.js Frontend               │
│  Upload → Live Agent Logs → Report + Export │
└──────────────────────┬──────────────────────┘
                       │ HTTP / WebSocket
┌──────────────────────▼──────────────────────┐
│              FastAPI Backend                │
│                                             │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  │
│  │ Surveyor │→ │Librarian │→ │ Auditor  │  │
│  │          │  │          │  │          │  │
│  │ Scans    │  │ Retrieves│  │ Generates│  │
│  │ title    │  │ building │  │compliance│  │
│  │ blocks   │  │ codes    │  │ report   │  │
│  └──────────┘  └──────────┘  └──────────┘  │
│                                             │
│  PDF Processing (PyMuPDF + pdfplumber)      │
│  Mock Code DB + Optional: UpCodes API       │
│  Export: PDF (ReportLab) + CSV              │
└─────────────────────────────────────────────┘
```

## Agent Workflow

### Agent 1: The Surveyor
- Extracts text from all pages with focus on title blocks (bottom-right corner)
- Identifies city, county, state, governing authority
- Detects seismic zone, wind zone, flood zone
- Determines plan type (commercial/residential/industrial)
- Falls back to heuristic extraction if LLM unavailable

### Agent 2: The Librarian
- Retrieves applicable building codes for the jurisdiction
- Covers: IBC, IFC, NEC, IPC, IMC, ADA, and state-specific amendments
- California: seismic requirements, CALGreen, WUI fire codes
- Florida: hurricane straps, HVHZ wind requirements
- New York, Texas, Washington: local amendments
- Optionally integrates with UpCodes API for real code data

### Agent 3: The Auditor
- Rule-based dimensional checks (corridor widths, door clearances, stair widths, ceiling heights)
- AI-assisted procedural checks (sprinklers, egress counts, ADA compliance)
- Generates findings with: status, severity, plan value vs. required value
- Provides actionable recommendations per finding
- Scores overall compliance (0–100%)

---

## Quick Start

### Prerequisites
- Python 3.11+
- Node.js 20+
- Docker + Docker Compose (for full stack)

### Option A: Docker Compose (Recommended)

```bash
# 1. Clone and configure
cp backend/.env.example backend/.env
# Edit backend/.env and set OPENAI_API_KEY

# 2. Start everything
docker-compose up -d

# 3. Open the app
open http://localhost:3000
```

### Option B: Local Development

**Backend:**
```bash
cd backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Set OPENAI_API_KEY in .env

uvicorn app.main:app --reload --port 8000
```

**Frontend:**
```bash
cd frontend
npm install
cp .env.local.example .env.local
npm run dev
```

---

## Environment Variables

### Backend (`.env`)

| Variable | Required | Description |
|---|---|---|
| `OPENAI_API_KEY` | Yes | OpenAI API key for GPT-4o |
| `SECRET_KEY` | Yes | JWT signing secret (32+ chars) |
| `DATABASE_URL` | No | PostgreSQL URL (defaults to SQLite for dev) |
| `REDIS_HOST` | No | Redis host for caching |
| `QDRANT_HOST` | No | Qdrant vector DB host |
| `UPCODES_API_KEY` | No | UpCodes.com API key for real code data |
| `SENTRY_DSN` | No | Sentry error tracking DSN |

> **Note:** Without an `OPENAI_API_KEY`, agents run in mock mode — jurisdiction extraction and LLM analysis are skipped, but rule-based compliance checks still work.

### Frontend (`.env.local`)

| Variable | Default | Description |
|---|---|---|
| `NEXT_PUBLIC_API_URL` | `http://localhost:8000` | Backend API URL |
| `NEXT_PUBLIC_WS_URL` | `ws://localhost:8000` | WebSocket URL |

---

## API Reference

```
POST   /api/v1/upload              Upload PDF → returns job_id
GET    /api/v1/jobs/{id}           Get job status + report
GET    /api/v1/jobs/{id}/logs      Get all agent logs
GET    /api/v1/jobs/{id}/export/pdf  Download PDF report
GET    /api/v1/jobs/{id}/export/csv  Download CSV report
DELETE /api/v1/jobs/{id}           Delete job
GET    /api/v1/jobs                List recent jobs

WS     /api/v1/ws/{id}             Real-time log streaming
GET    /health                     Health check
GET    /docs                       Swagger UI
```

---

## Building Code Coverage

| Code | Version | Coverage |
|---|---|---|
| IBC — International Building Code | 2021 | Egress, corridors, doors, occupancy, ceiling heights |
| IFC — International Fire Code | 2021 | Sprinklers, emergency egress |
| NEC — National Electrical Code | 2023 | GFCI, panels, conductors |
| IPC — International Plumbing Code | 2021 | Fixture counts |
| IMC — International Mechanical Code | 2021 | Ventilation rates |
| ADA Accessibility Guidelines | 2010 | Routes, doors, ramps, parking |
| California Building Code (CBC) | 2022 | Seismic, CALGreen, WUI, EV charging |
| Florida Building Code (FBC) | 2023 | Wind loads, hurricane, flood |
| NYC Building Code | 2022 | Local amendments |

---

## Testing

```bash
cd backend

# Run all tests
pytest tests/ -v

# Run with coverage
pytest tests/ -v --cov=app --cov-report=html

# Run specific test class
pytest tests/test_agents.py::TestAuditorAgent -v
```

---

## Production Deployment

See `infrastructure/kubernetes/` for Kubernetes manifests and `infrastructure/terraform/` for cloud provisioning.

```bash
# Apply k8s manifests
kubectl apply -k infrastructure/kubernetes/

# Check deployment
kubectl get pods -n ai-plan-checker
kubectl get hpa -n ai-plan-checker
```

---

## Extending

### Add a New Code Requirement
Edit `backend/app/services/code_database.py`:
```python
BUILDING_CODES_DB["IBC"]["requirements"].append({
    "code_id": "IBC-1234.5",
    "code_name": "International Building Code",
    "section": "1234.5",
    "description": "Your new requirement",
    "category": "fire_safety",  # or structural/electrical/plumbing/accessibility/energy/general
    "requirement_type": "dimension",  # or procedure/load/general
    "min_value": 36,
    "unit": "inches",
    "jurisdiction_specific": False,
})
```

### Connect UpCodes API
Set `UPCODES_API_KEY` in your `.env`. The `LibrarianAgent` will automatically prefer real code data from the API over the mock database.

### Add a New State
Add to `STATE_AMENDMENTS` in `code_database.py` following the existing CA/FL pattern.

---

## License

MIT — See LICENSE for details.
