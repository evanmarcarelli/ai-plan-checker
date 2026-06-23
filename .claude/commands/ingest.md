---
description: Grow or validate the jurisdiction code corpus through the corpus-ingest department — add a city/county, fill a gap, or drive the DGS amendment backlog. Verifies the result loads; respects the no-Cloudflare-bypass / no-ICC-scraping policy.
argument-hint: "<jurisdiction or target, e.g. 'pasadena_ca' or 'california --list'>"
---

Ingest or validate corpus coverage for: `$ARGUMENTS`.

Dispatch the `corpus-ingest` subagent. It should:

1. **Locate the target.** If the request is vague, run `cd backend && python -m app.code_library.ingest list` (and `california --list` for amendments) and identify the right publisher + `source_id`.
2. **Test run first.** A capped run before a full pull, e.g. `python -m app.code_library.ingest <publisher> --jurisdiction <slug> --max 50`.
3. **Verify (free gate).** Corpus reloads without error and chunk count rises; shrink-guard didn't trip; category spread is sane; `pytest tests/test_code_store.py` green.
4. **Full pull**, then re-verify.

## Rules
- No Cloudflare bypass; no ICC scraping (licensed → `licensed-pdf` from a local copy only). Prefer free government/edict sources.
- Report chunks written + before/after corpus size; append to `docs/optimization-log.md`.
- A jurisdiction is "done" only when a reviewer can retrieve its sections — spot-check one expected section.
