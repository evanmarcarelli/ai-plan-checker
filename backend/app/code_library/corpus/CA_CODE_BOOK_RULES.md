# CA Code Book Corpus Rules

## 1. What counts as up-to-date
State-level code books are current when their edition matches the current
adopted cycle in `../adoption/adoption_map.yaml` for the discipline:

| Discipline | Up-to-date edition       | Effective date     |
|------------|--------------------------|--------------------|
| CBC        | 2025 (T24 Part 2)        | 2026-01-01         |
| CRC        | 2025 (T24 Part 2.5)      | 2026-01-01         |
| CEBC       | 2025 (T24 Part 10)       | 2026-01-01         |
| CFC        | 2025 (T24 Part 9)        | 2026-01-01         |
| CEC        | 2025 (T24 Part 6)        | adopted edition     |

Entries whose year predates the adopted cycle are superseded for this corpus
and should not be promoted as current sources.

## 2. Internet Archive source rule
An IA item may become a corpus source only when:
- it is the official state-published edition, and
- its edition year matches the up-to-date edition above, and
- no duplicate corpus artifact already exists with the same discipline,
  edition, and scope.

Archive identifiers and filenames are the stable source keys in corpus docs;
do not replace an existing corpus file with an IA alias if the content is
already present under a project canonical name.

## 3. Duplicate rule
A code-book source is a duplicate when its content scope, edition, and
discipline duplicate an already present corpus file or registered ingest
source. Resolve duplicates by:
1. preserving the canonical corpus file already referenced from the project,
2. noting the IA source as an alternative retrieval URL only,
3. never creating a second corpus layer for the same discipline+edition+scope.

## 4. Internet Archive registry for up-to-date CA sources
These archive identifiers are the approved retrieval sources for the
state-level CA code books. Additions are permitted only when they match an
entry in the `jurisdictions.yaml` publisher/kind mapping or the
`adoption_map.yaml` adoption record, and only when the edition is current per
Section 1.

| Code  | Archive identifier              | Corpus artifact / status                             |
|-------|---------------------------------|------------------------------------------------------|
| CBC   | gov.ca.bsc.building.1.2025 + gov.ca.bsc.building.2.2025 | `ca_cbc_2025.jsonl` PRESENT (7,666 chunks; combined Part 1 + Part 2 born-digital state edition; `source_tier=licensed`, `license_status=licensed`). Errata present as `ca_cbc_2025_errata_vol1.jsonl` and `ca_cbc_2025_errata_vol2.jsonl`. NOTE: in the 2025 cycle **CBC Chapter 7A is now a 2-page pointer stub** — the WUI provisions were relocated to the California Wildland-Urban Interface Code (Title 24 Part 7); see the CBC-7A row and CBC §101.4.8. So `7xxA` sections are intentionally absent from this CBC file (not an extraction failure). |
| CBC-7A | gov.ca.bsc.wildland.2025       | `ca_cbc_7a_2025.jsonl` PRESENT (280 chunks; `code_short=CBC-7A`; `source_tier=licensed`). The adopted **2025 California Wildland-Urban Interface Code** (T24 Pt 7) — the WUI provisions formerly in CBC Chapter 7A, **renumbered** (e.g. old 709A "Decking" → 504.7.3; 705A roofing → 504.2; 708A vents → 504.10; glazing → 504.8). A correlation table inside the doc maps legacy `7xxA` → new numbers. `FIRE-WUI-DECK` now cites `CBC-7A 504.7.3`. |
| CRC   | gov.ca.bsc.residential.2025     | `ca_crc_2025.jsonl` present; archive ref registered   |
| CEBC  | gov.ca.bsc.existing.2025        | `ca_cebc_2025.jsonl` present; archive ref registered  |
| CFC   | gov.ca.bsc.fire.2025            | Missing corpus file; add when ingest branch is created|
| CEC   | energy-code (CEC-400-2025-010-F) | `ca_energy_code_2025.jsonl` present; IA not needed   |

## 5. Update protocol
Before adding a source, confirm the current adopted edition in
`adoption/adoption_map.yaml` and mark `[verify]` entries with the edition
year. Do not add a new corpus file for a code book that already exists under
a canonical filename; instead update the corresponding registry row with the
canonical filename.
