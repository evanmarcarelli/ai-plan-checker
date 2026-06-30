# CA Book Corpus Audit (2025 State Code Books)

## Scope
Compare desired 2025 CA state code-book corpus against actual files in
`backend/app/code_library/corpus/`.

## Desired state
Based on `corpus/CA_CODE_BOOK_RULES.md` Section 4.

| Code | Canonical filename              | Status       |
|------|---------------------------------|--------------|
| CBC  | `ca_cbc_2025.jsonl`            | OK           |
| CBC  | `ca_cbc_2025_errata_vol1.jsonl`| OK           |
| CBC  | `ca_cbc_2025_errata_vol2.jsonl`| OK           |
| CBC-7A | `ca_cbc_7a_2025.jsonl`        | OK (CA Wildland-Urban Interface Code, T24 Pt 7) |
| CRC  | `ca_crc_2025.jsonl`            | OK           |
| CRC  | `ca_crc_2025_errata.jsonl`     | OK           |
| CEBC | `ca_cebc_2025.jsonl`            | OK           |
| CEBC | `ca_cebc_2025_errata_*.jsonl`   | Not tracked yet in CA book rules |
| CFC  | TBD (see patch plan)            | MISSING      |
| CFC  | `ca_cfc_2025_errata_*.jsonl`   | Not tracked yet in CA book rules |
| CEC  | `ca_energy_code_2025.jsonl`    | OK           |

## Notes
- `ca_cbc_2025.jsonl` was produced 2026-06-30 from the born-digital state edition on
  Internet Archive (`gov.ca.bsc.building.1.2025` Part 1 + `gov.ca.bsc.building.2.2025`
  Part 2), ingested via `python -m app.code_library.ingest licensed-pdf` and tagged
  `source_tier=licensed` / `license_status=licensed`. 7,666 chunks (Part 1 = 4,122
  architectural/life-safety ch. 1–15; Part 2 = 3,544 structural ch. 16–35). Loads cleanly
  (0 bad lines). NOTE: 2025 CBC Chapter 7A is now a 2-page pointer stub — the WUI provisions
  were relocated to the standalone California Wildland-Urban Interface Code (T24 Part 7), so
  no `7xxA` sections are in this CBC file by design (not an extraction failure).
- `ca_cbc_7a_2025.jsonl` was produced 2026-06-30 from `gov.ca.bsc.wildland.2025` (the adopted
  2025 California Wildland-Urban Interface Code, T24 Part 7) via the same `licensed-pdf` ingest
  (`code_short=CBC-7A`, `source_tier=licensed`). 280 chunks of real WUI provisions (roofing,
  vents, walls, glazing, decking, defensible space) under the WUI Code's own renumbering
  (legacy CBC `7xxA` → new `4xx/5xx`; e.g. 709A decking → 504.7.3). This is what backs the
  `FIRE-WUI-DECK` rule (`CBC-7A 504.7.3`).
- `ca_cec_2025_errata.jsonl` exists in corpus but is not yet documented in the CA book rules.
- `ca_archive_ia_existing_2025.jsonl` is present; see CA book rules for its relationship to CEBC 2025.
