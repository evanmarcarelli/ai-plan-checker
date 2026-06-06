# AWS Textract Setup Guide

## What it does

AWS Textract is the OCR layer between PyMuPDF (free, fast, works when the
PDF has a real text layer) and Claude vision (smart but expensive). When a
plan-set page is image-only — typical for scanned legacy drawings or
plans exported as raster PDFs — PyMuPDF returns nothing useful and every
department reviewer comes back `needs_review` because the structured plan
data is empty.

Textract fills that gap. On those pages it:

1. **OCRs the page text** so dimensions, notes, and labels are searchable.
2. **Extracts the code-data summary table** as structured key→value pairs
   (occupancy, construction type, building height, total area, etc.)
   that flow directly into the surveyor's `ExtractedPlanData`.

The result: scanned plan sets work the same as native PDFs.

## Cost

| Mode | Price | When it fires |
|---|---|---|
| `analyze_document` with TABLES + FORMS | **$0.065 per page** | Per page that fails the text-layer threshold |
| Doing nothing | $0.00 | Per page whose text layer extracts cleanly |
| Doing nothing | $0.00 | When the flag is off |

Cost per plan depends on how scan-heavy it is:

| Plan set | Thin pages OCR'd | Cost per plan |
|---|---|---|
| 25-page mostly-native PDF (3–5 scans) | 3–5 | $0.20 – $0.35 |
| 50-page hybrid plan set | ~15 | ~$1.00 |
| 100-page scanned legacy set (every page) | 100 | ~$6.50 |
| 200-page scanned set | 200 | ~$13.00 |

**No page cap by default** (`TEXTRACT_MAX_PAGES=0`) — every thin page goes
through OCR so the full plan set is covered. Set `TEXTRACT_MAX_PAGES` to a
positive integer if a workflow needs a hard spend ceiling per plan.

## One-time setup

### 1. Create the IAM user in AWS

1. AWS Console → **IAM** → **Users** → **Create user**.
2. Username: `up2code-textract` (or anything memorable).
3. **Attach policies directly** → search for and check **`AmazonTextractFullAccess`**.
   (Scoped equivalent: a custom policy granting only `textract:AnalyzeDocument`
   and `textract:DetectDocumentText`. The full-access policy is fine for now;
   tighten later.)
4. Create user.

### 2. Generate the access key

1. Click the new user → **Security credentials** tab → **Create access key**.
2. Use case: **Application running outside AWS**.
3. Copy both values immediately — the secret is shown **once**.
   - `Access key ID` — looks like `AKIA…`
   - `Secret access key` — looks like a long random string

### 3. Paste them into Render

In the `up2code-backend` service on Render → **Environment** → **Add Environment Variable**:

```
AWS_TEXTRACT_ENABLED   = true
AWS_ACCESS_KEY_ID      = <the AKIA… value>
AWS_SECRET_ACCESS_KEY  = <the secret>
AWS_REGION             = us-west-2     # already in render.yaml; only change if you know why
```

Optional tuning:
```
TEXTRACT_MIN_CHARS_PER_PAGE = 200      # raise to OCR more pages, lower to OCR fewer
TEXTRACT_MAX_PAGES          = 0        # 0 = no cap; set to a positive int to bound spend per plan
```

### 4. Redeploy

Render env-var changes do NOT apply to the running instance. After saving:

- Click **Manual Deploy** → **Deploy latest commit**, OR
- Click **Restart Service** (faster, same effect for env-only changes).

### 5. Smoke test

Open in a browser:

```
https://<your-render-backend>.onrender.com/api/v1/_diag/textract
```

Expected:

```json
{ "status": "OK", "hint": "Textract auth + AnalyzeDocument permission verified. OCR fallback is live." }
```

If you see anything else, the JSON's `error` and `hint` fields tell you what to fix.

## Common failure modes

| Symptom | Cause | Fix |
|---|---|---|
| `status: "DISABLED"` | `AWS_TEXTRACT_ENABLED=false` | Set to `true`, redeploy |
| `status: "NO_KEY"` | One of the env vars is blank | Paste both keys, redeploy |
| `error_type: "UnrecognizedClientException"` | Wrong AWS account or stray whitespace in the keys | Re-copy from IAM and re-paste cleanly |
| `error: "AccessDenied"` | IAM user missing `textract:AnalyzeDocument` | Attach `AmazonTextractFullAccess` |
| `error: "could not be found"` | Region typo | Use `us-west-2` or `us-east-1` |
| `enabled_flag: true` but plans still fail | Pages above the threshold; Textract not invoked | Lower `TEXTRACT_MIN_CHARS_PER_PAGE` (try 500) |

## How to confirm it's actually firing on a real plan

1. Run an analysis on a scanned plan set.
2. SSH to Render → Logs, search for `[textract]`.

Expected log lines:
```
[textract] OCR done — attempted=4 succeeded=4 kvs=6
[Surveyor] Textract code_data_summary populated 6 field(s): ['occupancy', 'construction_type', 'building_height', 'building_area', 'project_address', 'stories']
```

If you see `attempted=0`, every page passed the text-layer threshold and
Textract is correctly *not* spending money on them. If you see
`succeeded=0` while `attempted>0`, look at the error preceding it (auth
or throttling are the usual two).

## Architecture notes

- Textract runs in `pdf_processor.extract()`, **after** PyMuPDF and **before**
  the surveyor's Claude-vision pass. PyMuPDF stays the fast path; Textract
  is the structured-OCR middle tier; vision is the last-resort reasoning
  layer. All three layers compose — anything Textract reads confidently
  off the code-data box short-circuits the vision call from having to.
- The service uses Textract's **sync per-page** API (`analyze_document`)
  after rendering each target page to PNG via PyMuPDF. We deliberately
  avoid the **async multi-page PDF** API (`start_document_analysis`) so
  there's no S3 dependency, no polling, no SNS topic to provision — one
  IAM user and you're done.
- All Textract-related code is import-lazy. The module imports `boto3`
  only on first use, so an environment missing the dependency or the
  feature flag never pays the import cost or risks a startup failure.
