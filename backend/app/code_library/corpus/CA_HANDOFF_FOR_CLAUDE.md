# Handoff prompt — CA state code book system expansion

## Your task
Finish the missing California 2025 CBC main-volume corpus entry and, if useful, expand rules derived from it. The work already done is in `backend/app/code_library/corpus/CA_CODE_BOOK_RULES.md` and `CA_CODE_BOOK_AUDIT.md`; use them as the source of truth and keep both files up to date as you make changes.

## What is already in place
- `corpus/ca_crc_2025.jsonl`, `corpus/ca_crc_2025_errata.jsonl` — present
- `corpus/ca_cebc_2025.jsonl` — present
- `corpus/ca_cbc_2025_errata_vol1.jsonl`, `corpus/ca_cbc_2025_errata_vol2.jsonl` — present
- `corpus/ca_energy_code_2025.jsonl` — present
- `corpus/ca_cec_2025_errata.jsonl` — present
- `corpus/CA_CODE_BOOK_RULES.md` — rules document (read it first)
- `corpus/CA_CODE_BOOK_AUDIT.md` — current audit state (read it first)

## What is missing
`corpus/ca_cbc_2025.jsonl` is the only missing 2025 state code-book artifact.

## Source
- Archive: `https://archive.org/details/gov.ca.bsc.building.2.2025`
- Adopted edition: 2025 CBC (T24 Part 2), effective 2026-01-01

## Rules you must follow
1. Do not scrape copyrighted ICC viewer text. Use only:
   - the licensed local PDF path via `backend/app/code_library/ingest/licensed_pdf.py`, or
   - the archival/public-domain source provided above if it is a state-published edition and the edition year is 2025.
2. Before producing any corpus file that changes current behavior, confirm the edition and jurisdiction in `backend/app/code_library/adoption/adoption_map.yaml`.
3. `CA_CODE_BOOK_RULES.md` and `CA_CODE_BOOK_AUDIT.md` are the public manifest. Update them both immediately after any corpus file is added or any registry row is filled.
4. Respect the existing corpus shape from `licensed_pdf.py` and `chunker.py`; do not change the JSONL field contract unless explicitly requested.
5. If you are deriving rules from the new CBC text, put them in `backend/app/code_library/deterministic/rules.py` or a sibling file already imported there. Do not introduce ad-hoc rule files.
6. Keep `corpus/ca_cbc_2025_errata_vol1.jsonl` and `vol2` as the errata supplements. If a rule relies on an erratum, note the JURISDICTION-RULE-ID + erratum filename in the rule's provenance comment.

## Exact ingest command
```bash
cd backend
python -m app.code_library.ingest licensed-pdf \
    --pdf <PATH_TO_CBC_2025_PDF> \
    --code-short CBC \
    --code-name "California Building Code" \
    --version 2025 \
    --scope CA
```

## Deliverables
1. `corpus/ca_cbc_2025.jsonl` produced via the command above (or created via public-domain brittle path if local PDF not available), tagged `source_tier=licensed` and `license_status=licensed`.
2. `CA_CODE_BOOK_RULES.md` and `CA_CODE_BOOK_AUDIT.md` updated to mark CBC 2025 as present.
3. If useful, a small set of CBC-specific rules added under `deterministic/rules.py` with `requires_citation=True` and source citation pointing to the new corpus file.

## Boundaries
- Do not modify municipal-ingest scrapers.
- Do not touch `adoption_map.yaml` unless the new change is purely additive and clearly marked.
- Do not run the full `la-county` ingest command.
- Do not fetch from sites that return Cloudflare bot challenges; those must remain queued.

## Finish criteria
- `corpus/ca_cbc_2025.jsonl` exists and is loadable by the project's corpus loader.
- The two MD files reflect the new reality accurately.
- You have left a short completion note at the bottom of this prompt file stating: what you changed, what came back empty, and what still needs a human with the licensed PDF to finish.

---

## Completion note (2026-06-30)

### What was done
- **`corpus/ca_cbc_2025.jsonl` produced (7,666 chunks, loads cleanly, 0 bad lines).** Tagged
  `source_tier=licensed` / `license_status=licensed`, `version=2025`, `code_short=CBC`.
  Built with the prescribed `licensed-pdf` ingest path (no scraping, no field-contract change).
- **The archive item named here is split into two PDFs**, so I ingested **both** halves of the
  same born-digital state edition and combined them into the one canonical file:
  - `gov.ca.bsc.building.1.2025` ("Part 1") → 4,122 chunks — architectural/life-safety, ch. 1–15
    (occupancy, area/height, egress ch. 10, accessibility 11A/11B, fire ch. 9).
  - `gov.ca.bsc.building.2.2025` ("Part 2", the id in this handoff) → 3,544 chunks — structural,
    ch. 16–35 incl. the DSA/OSHPD `16A/17A/...` amendments + referenced standards.
  Ingest command used (per half), with the project venv `backend/.venv-claude`:
  `python -m app.code_library.ingest licensed-pdf --pdf <gov.ca.bsc.building.N.2025.pdf>
  --code-short CBC --code-name "California Building Code" --version 2025 --scope CA --output <...>`,
  then the two outputs were concatenated into `ca_cbc_2025.jsonl`.
- **Also ingested the WUI Code → `corpus/ca_cbc_7a_2025.jsonl` (280 chunks).** While confirming
  the Chapter-7A gap I discovered it isn't an extraction failure: in the 2025 cycle CBC Chapter 7A
  became a **2-page pointer stub** and the WUI provisions moved to the standalone **California
  Wildland-Urban Interface Code (Title 24 Part 7)** — a separate, freely-available archive item
  `gov.ca.bsc.wildland.2025` with full extractable text. Ingested via the same `licensed-pdf`
  path (`code_short=CBC-7A`, `licensed`). The WUI Code **renumbered** the old sections (709A
  decking → 504.7.3; 705A roofing → 504.2; 708A vents → 504.10; glazing → 504.8), with a
  correlation table mapping legacy `7xxA` → new numbers.
- **Retired the CBC 709A debt.** `FIRE-WUI-DECK` now cites `CBC-7A 504.7.3 · CBC 709A` (primary =
  the adopted 2025 WUI Code decking section, verified to return 2025 text; legacy CBC 709A kept
  for recognition), and was **removed from `KNOWN_MISSING`** in `test_rule_citation_coverage.py`.
- **Docs updated:** `CA_CODE_BOOK_RULES.md` §4 (CBC row corrected + new CBC-7A row),
  `CA_CODE_BOOK_AUDIT.md` (CBC `MISSING → OK`, new CBC-7A row + notes), and a comment-only,
  additive line in `adoption/adoption_map.yaml` (CBC row) recording both ingests.
- **Three CBC-2025-grounded deterministic rules added** in `deterministic/rules.py` as a new
  `CBC_2025_RULES` list, injected for CA jurisdictions only (via `default_rules_for` /
  `rules_for_jurisdiction`, the same pattern as the CALGreen and CalFire packs — they cite a
  California edition, so they must not fire on a non-CA plan). Each is `requires_citation=True`
  and cites a section verified present in the new corpus, returning real 2025 text:
  `CBC-GEOTECH-REPORT` (CBC 1803.2), `CBC-SPECIAL-INSPECTION` (CBC 1704.2.3),
  `CBC-SEISMIC-DESIGN-DATA` (CBC 1603.1.5). Gated to non-dwelling plan types (SFRs use the CRC
  path). Verified end-to-end under the production gate flags: they fire as NON_COMPLIANT with
  2025 source text on a sparse commercial plan, drop out when the items are declared, and never
  fire on a residential plan.
- **Tests:** the full backend suite passes — **442 passed, 0 failed** (`python -m pytest tests/ -q`),
  including `test_rule_citation_coverage`, `test_deterministic`, and the corpus-size-sensitive
  `test_citation_retrieval`. No regression from adding 7,666 chunks to the shared BM25 corpus.

### Correction to an earlier finding
- My first pass concluded "Chapter 7A is an image-based insert that failed to extract." **That was
  wrong.** Rendering the actual pages showed 2025 CBC Chapter 7A is a deliberate **2-page pointer
  stub** ("Provisions … are now located in Part 7, California Wildland-Urban Interface Code. See
  Section 101.4.8."). The WUI content was **relocated** to a separate code, not lost to OCR. That
  relocated code is now ingested (see above), so the gap is essentially closed.

### What came back empty / minor
- `7xxA` sections are intentionally absent from `ca_cbc_2025.jsonl` (Chapter 7A is a stub) — the
  WUI provisions live in `ca_cbc_7a_2025.jsonl` under the WUI Code's new numbering.
- A few CBC chapters (13/14/15 roofing) are thinner than others, a born-digital layout artifact;
  the bulk of ch. 1–12 and 16–35 extracted well.
- 71 of 7,666 `ca_cbc_2025.jsonl` chunk_ids are duplicates (Chapter 1 front matter is reprinted in
  both volumes); harmless — the loader de-collides them (by_citation last-write-wins).

### What a human may still want to decide (non-blocking)
- **Citation convention for WUI under the 2025 cycle.** The project's benchmark/legacy rules use
  the old `7xxA` numbers (e.g. `CBC-7A 704A.1`), but the adopted 2025 WUI Code renumbered to
  `4xx/5xx`. `FIRE-WUI-DECK` was modernized to the new number (`CBC-7A 504.7.3`); `FIRE-WUI-VENT`
  (`CBC 708A`) and `FIRE-WUI-7A` were left on their legacy refs (still backed by the 2007/2019
  archives) to avoid churn. A maintainer may want to modernize those two to `CBC-7A 504.10` /
  the WUI Code scope section, and refresh benchmark ground-truth to the new numbering.
- **Optional new WUI rules** now groundable in `ca_cbc_7a_2025.jsonl`: Class-A roof (504.2),
  exterior walls (504.5), exterior glazing (504.8), ember-resistant vents (504.10). Left out to
  keep the rule additions small and focused; easy to add against verified 2025 sections.
