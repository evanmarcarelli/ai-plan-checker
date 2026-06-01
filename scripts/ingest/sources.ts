// =====================================================================
// Ingest source definitions — CA base codes (Session A)
//
// Defines every code document that gets chunked + embedded into the
// code_chunks table. Run `pipeline.ts` to execute the ingest.
//
// SOURCE STRATEGY
// ---------------
// Primary source: up.codes viewer (clean structured HTML, each section
// at a stable URL). The ingest pipeline fetches section-level pages
// and treats each section as one chunk.
//
// Official source (fallback / verification): California Building
// Standards Commission (bsc.ca.gov) publishes free PDFs. Use these
// when up.codes diverges from the official text.
//
// For a production deployment, consider licensing the BSC official
// content directly (contact licensing@bsc.ca.gov) to eliminate any
// reliance on third-party viewer sites.
// =====================================================================

export interface CodeSource {
  // Identifies this source in the code_chunks table
  corpusKey: string;            // e.g. 'CBC:2022'
  jurisdictionKey: string;      // 'CA' for all CA base codes
  codeName: string;             // 'California Building Code 2022'
  codeYear: string;             // '2022'
  part: string | null;          // 'Part 2', 'Part 6', null
  // Where to start fetching — the TOC (table of contents) root URL.
  // The pipeline follows links from this page to individual sections.
  tocUrl: string;
  // Fallback: official BSC or other .gov PDF
  officialPdfUrl: string | null;
  // How to identify section boundaries in the fetched HTML
  sectionUrlPattern: RegExp;   // matches URLs that are individual sections
  // Chapters to include. Empty = all chapters.
  chaptersToInclude?: string[];
  // Chapters to skip (e.g. appendices with duplicate table content)
  chaptersToSkip?: string[];
  // Approximate chunk count (for progress display)
  estimatedChunks: number;
  note?: string;
}

// =====================================================================
// CA base code sources (~1,100 chunks total)
//
// up.codes URL pattern for CA codes:
//   TOC:     https://up.codes/viewer/california/{code-slug}
//   Section: https://up.codes/viewer/california/{code-slug}/{section-id}
//
// Each section page has the section text in the main <article> element.
// =====================================================================

export const CA_BASE_CODE_SOURCES: CodeSource[] = [

  // ------------------------------------------------------------------
  // California Building Code 2022 (CBC) — Title 24, Part 2
  // ~400 important sections; ingest Volumes 1 & 2
  // Key chapters for plan review: 3, 4, 5, 7A, 9, 10, 11A, 11B
  // ------------------------------------------------------------------
  {
    corpusKey: "CBC:2022",
    jurisdictionKey: "CA",
    codeName: "California Building Code 2022",
    codeYear: "2022",
    part: "Part 2",
    tocUrl: "https://up.codes/viewer/california/ca-building-code-2022",
    officialPdfUrl: "https://www.dgs.ca.gov/BSC/Codes/Page-Content/Codes-Page-List/2022-California-Building-Code",
    sectionUrlPattern: /up\.codes\/viewer\/california\/ca-building-code-2022\/[a-z0-9-]+/i,
    chaptersToInclude: [
      "chapter-1",  // Administration
      "chapter-2",  // Definitions
      "chapter-3",  // Use and Occupancy
      "chapter-4",  // Special Detailed Requirements
      "chapter-5",  // General Building Heights and Areas
      "chapter-6",  // Types of Construction
      "chapter-7",  // Fire and Smoke Protection Features
      "chapter-7a", // Wildfire Exposure (WUI) — key for CA
      "chapter-9",  // Fire Protection Systems (sprinklers, alarm)
      "chapter-10", // Means of Egress
      "chapter-11a",// Accessibility — CalDAG (CA-specific)
      "chapter-11b",// Accessibility — CA specific
      "chapter-16", // Structural Design
      "chapter-17", // Special Inspection
      "chapter-18", // Soils and Foundations
      "chapter-23", // Wood
      "chapter-25", // Gypsum Board
      "chapter-26", // Plastic
      "chapter-31", // Special Construction
      "chapter-33", // Safeguards During Construction
    ],
    estimatedChunks: 400,
    note: "CA-specific chapters 7A, 11A, 11B are critical for CA plan review. Prioritize these.",
  },

  // ------------------------------------------------------------------
  // California Residential Code 2022 (CRC) — Title 24, Part 2.5
  // Governs SFR and duplexes (1-2 family, 3 stories max).
  // Critical for the ADU plan volume that drives CA permit activity.
  // ------------------------------------------------------------------
  {
    corpusKey: "CRC:2022",
    jurisdictionKey: "CA",
    codeName: "California Residential Code 2022",
    codeYear: "2022",
    part: "Part 2.5",
    tocUrl: "https://up.codes/viewer/california/ca-residential-code-2022",
    officialPdfUrl: "https://www.dgs.ca.gov/BSC/Codes/Page-Content/Codes-Page-List/2022-California-Residential-Code",
    sectionUrlPattern: /up\.codes\/viewer\/california\/ca-residential-code-2022\/[a-z0-9-]+/i,
    chaptersToInclude: [
      "chapter-1",   // Administration
      "chapter-2",   // Definitions
      "chapter-3",   // Building Planning (R301 fire, R310 egress, R317 WUI)
      "chapter-4",   // Foundations
      "chapter-5",   // Floors
      "chapter-6",   // Wall Construction
      "chapter-7",   // Wall Covering
      "chapter-8",   // Roof-Ceiling Construction
      "chapter-9",   // Roof Assemblies
      "chapter-10",  // Chimneys and Fireplaces
      "chapter-11",  // Energy Efficiency (CEC cross-ref)
      "chapter-25",  // Plumbing cross-reference
      "chapter-36",  // Electrical cross-reference
      "chapter-44",  // Referenced Standards
      "appendix-q",  // Tiny Houses (increasingly relevant in CA)
    ],
    estimatedChunks: 250,
    note: "R317 (WUI), R310 (emergency escape), R302 (fire separation) are the highest-value sections for CA ADU review.",
  },

  // ------------------------------------------------------------------
  // California Mechanical Code 2022 (CMC) — Title 24, Part 4
  // ------------------------------------------------------------------
  {
    corpusKey: "CMC:2022",
    jurisdictionKey: "CA",
    codeName: "California Mechanical Code 2022",
    codeYear: "2022",
    part: "Part 4",
    tocUrl: "https://up.codes/viewer/california/ca-mechanical-code-2022",
    officialPdfUrl: "https://www.dgs.ca.gov/BSC/Codes/Page-Content/Codes-Page-List/2022-California-Mechanical-Code",
    sectionUrlPattern: /up\.codes\/viewer\/california\/ca-mechanical-code-2022\/[a-z0-9-]+/i,
    chaptersToInclude: [
      "chapter-1",  // Administration
      "chapter-2",  // Definitions
      "chapter-3",  // General Regulations
      "chapter-4",  // Ventilation Air
      "chapter-6",  // Duct Systems
      "chapter-9",  // Installation of Specific Appliances
      "chapter-10", // Boilers and Pressure Vessels
      "chapter-13", // Fuel Gas Piping
    ],
    estimatedChunks: 120,
  },

  // ------------------------------------------------------------------
  // California Plumbing Code 2022 (CPC) — Title 24, Part 5
  // ------------------------------------------------------------------
  {
    corpusKey: "CPC:2022",
    jurisdictionKey: "CA",
    codeName: "California Plumbing Code 2022",
    codeYear: "2022",
    part: "Part 5",
    tocUrl: "https://up.codes/viewer/california/ca-plumbing-code-2022",
    officialPdfUrl: "https://www.dgs.ca.gov/BSC/Codes/Page-Content/Codes-Page-List/2022-California-Plumbing-Code",
    sectionUrlPattern: /up\.codes\/viewer\/california\/ca-plumbing-code-2022\/[a-z0-9-]+/i,
    chaptersToInclude: [
      "chapter-1",  // Administration
      "chapter-2",  // Definitions
      "chapter-4",  // Plumbing Fixtures and Fixture Fittings
      "chapter-5",  // Water Heaters
      "chapter-6",  // Water Supply and Distribution
      "chapter-7",  // Sanitary Drainage
      "chapter-9",  // Vents
      "chapter-11", // Storm Drainage
    ],
    estimatedChunks: 100,
  },

  // ------------------------------------------------------------------
  // California Electrical Code 2022 (CEC) — Title 24, Part 3
  // CEC = NEC 2020 as adopted and amended by CA
  // ------------------------------------------------------------------
  {
    corpusKey: "CEC:2022",
    jurisdictionKey: "CA",
    codeName: "California Electrical Code 2022",
    codeYear: "2022",
    part: "Part 3",
    tocUrl: "https://up.codes/viewer/california/ca-electrical-code-2022",
    officialPdfUrl: "https://www.dgs.ca.gov/BSC/Codes/Page-Content/Codes-Page-List/2022-California-Electrical-Code",
    sectionUrlPattern: /up\.codes\/viewer\/california\/ca-electrical-code-2022\/[a-z0-9-]+/i,
    chaptersToInclude: [
      "chapter-1",  // General (Articles 90-110)
      "chapter-2",  // Wiring and Protection (Art 200-285)
      "chapter-3",  // Wiring Methods and Materials (Art 300-398)
      "chapter-4",  // Equipment for General Use (Art 400-490)
      "chapter-7",  // Special Conditions (Art 700-770)
      "chapter-9",  // Tables
    ],
    estimatedChunks: 130,
  },

  // ------------------------------------------------------------------
  // Title 24 Part 6 — California Energy Code 2022
  // Prescriptive and performance compliance paths for residential +
  // nonresidential. Critical for all CA submittals.
  // ------------------------------------------------------------------
  {
    corpusKey: "TITLE24:P6:2022",
    jurisdictionKey: "CA",
    codeName: "California Energy Code 2022 (Title 24 Part 6)",
    codeYear: "2022",
    part: "Part 6",
    tocUrl: "https://up.codes/viewer/california/ca-energy-code-2022",
    officialPdfUrl: "https://efts.energy.ca.gov/LAZARUS/publications/attachments/CEC-400-2021-014.pdf",
    sectionUrlPattern: /up\.codes\/viewer\/california\/ca-energy-code-2022\/[a-z0-9-]+/i,
    chaptersToInclude: [
      "chapter-1",  // Purpose and Scope
      "chapter-2",  // Definitions
      "chapter-3",  // Prescriptive Compliance
      "chapter-4",  // Performance Approach
      "chapter-5",  // Nonresidential Requirements
      "chapter-6",  // Residential Requirements
      "chapter-8",  // Compliance Documentation
      "appendix-na",// Alternative Component Package
    ],
    estimatedChunks: 180,
    note: "CEC compliance path declaration (prescriptive vs. performance) is required on every CA submittal.",
  },

  // ------------------------------------------------------------------
  // Title 24 Part 11 — CALGreen (California Green Building Standards)
  // ------------------------------------------------------------------
  {
    corpusKey: "TITLE24:P11:2022",
    jurisdictionKey: "CA",
    codeName: "CALGreen 2022 (Title 24 Part 11)",
    codeYear: "2022",
    part: "Part 11",
    tocUrl: "https://up.codes/viewer/california/ca-green-building-standards-code-2022",
    officialPdfUrl: "https://www.dgs.ca.gov/BSC/Codes/Page-Content/Codes-Page-List/2022-California-Green-Building-Standards-Code-CALGreen",
    sectionUrlPattern: /up\.codes\/viewer\/california\/ca-green-building-standards-code-2022\/[a-z0-9-]+/i,
    chaptersToInclude: [
      "chapter-1",  // Administration
      "chapter-2",  // Definitions
      "chapter-3",  // Residential Mandatory Measures
      "chapter-4",  // Nonresidential Mandatory Measures
      "chapter-5",  // Nonresidential Voluntary Tiers 1 & 2
      "appendix-a4",// Residential Voluntary Measures
      "appendix-a5",// Nonresidential Voluntary Measures
    ],
    estimatedChunks: 80,
  },

  // ------------------------------------------------------------------
  // CBC Chapter 7A — Wildfire-Resistive Construction Materials + PRC 4291
  // Targeted ingest of just this chapter (already in CBC:2022 above,
  // but duplicated here as a standalone corpus for fast WUI lookups).
  // ------------------------------------------------------------------
  {
    corpusKey: "CBC:2022:7A",
    jurisdictionKey: "CA",
    codeName: "CBC 2022 Chapter 7A — Wildfire-Resistive Construction",
    codeYear: "2022",
    part: "Part 2 Chapter 7A",
    tocUrl: "https://up.codes/viewer/california/ca-building-code-2022/chapter-7a-wildfire-exposure",
    officialPdfUrl: null,
    sectionUrlPattern: /up\.codes\/viewer\/california\/ca-building-code-2022\/(section-7[0-9]|chapter-7a)/i,
    estimatedChunks: 30,
    note: "Covers Sections 701A–710A. Applies to all projects in SRA/LRA Very High and High FHSZ zones.",
  },

  // ------------------------------------------------------------------
  // PRC 4291 — Defensible Space
  // California Public Resources Code §4291 — the statute-level
  // requirement for 100-ft defensible space around structures in
  // State Responsibility Areas. Pairs with CBC Chapter 7A.
  // ------------------------------------------------------------------
  {
    corpusKey: "PRC:4291",
    jurisdictionKey: "CA",
    codeName: "Public Resources Code §4291 — Defensible Space",
    codeYear: "2022",
    part: null,
    tocUrl: "https://leginfo.legislature.ca.gov/faces/codes_displaySection.xhtml?lawCode=PRC&sectionNum=4291.",
    officialPdfUrl: null,
    sectionUrlPattern: /leginfo\.legislature\.ca\.gov.*PRC.*429[0-9]/i,
    estimatedChunks: 10,
    note: "Statutory text (public domain); also covers 4291.1, 4292, 4293. Cite this for inspectors' defensible space check, not just the building code.",
  },
];

// =====================================================================
// National baseline + federal code sources (~970 chunks total)
//
// These are the model codes (IBC, NFPA, NEC, IPC, IMC, IECC) and federal
// standards (ADA) cited by BASELINE_RULES. The corpus search expands
// every jurisdiction-scoped query to also include "baseline" and
// "federal" keys (see expandJurisdictionKeys), so these chunks are
// searchable from any state/city project.
//
// URL strategy:
//   - Model codes use up.codes/viewer/florida/* — Florida adopts the
//     national I-Codes substantively unchanged, so its viewer is the
//     cleanest stable URL for verbatim national text. If FL diverges
//     for a future edition, switch to up.codes/viewer/idaho/* (similar
//     near-verbatim adoption profile).
//   - NFPA standards (13, 72) are hosted on nfpa.org under free
//     read-only access; ingest requires a session cookie. The TOC URL
//     here is the canonical landing page — pipeline operator should
//     pre-warm the session before running.
//   - ADA is federal public-domain text; the Access Board HTML version
//     is the authoritative source.
//
// ICC licensing: see docs/ICC_LICENSING.md. Storing up.codes-rendered
// chunks for internal retrieval is permitted; verbatim passages > 200
// chars must NOT be echoed in user-facing findings.
// =====================================================================

export const NATIONAL_CODE_SOURCES: CodeSource[] = [

  // ------------------------------------------------------------------
  // International Building Code 2021 (IBC) — dominant code_ref in BASELINE_RULES
  // Priority chapters drive >80% of active rules.
  // ------------------------------------------------------------------
  {
    corpusKey: "IBC:2021",
    jurisdictionKey: "baseline",
    codeName: "International Building Code 2021",
    codeYear: "2021",
    part: null,
    tocUrl: "https://up.codes/viewer/florida/ibc-2021",
    officialPdfUrl: null,
    sectionUrlPattern: /up\.codes\/viewer\/florida\/ibc-2021\/[a-z0-9-]+/i,
    chaptersToInclude: [
      "chapter-1",   // Administration / scope
      "chapter-2",   // Definitions
      "chapter-3",   // Use and Occupancy Classification (302–312)
      "chapter-4",   // Special Detailed Requirements (incl. 403 high-rise)
      "chapter-5",   // General Building Heights and Areas (Tables 504.4, 506.2)
      "chapter-6",   // Types of Construction (602)
      "chapter-7",   // Fire and Smoke Protection
      "chapter-9",   // Fire Protection Systems (sprinklers, alarm)
      "chapter-10",  // Means of Egress (1004, 1005, 1006, 1010)
      "chapter-11",  // Accessibility (defers to ICC A117.1)
      "chapter-16",  // Structural Design
      "chapter-27",  // Electrical (defers to NEC)
    ],
    estimatedChunks: 300,
    note: "Highest-priority source — 73% of BASELINE_RULES cite IBC. Ingest first.",
  },

  // ------------------------------------------------------------------
  // National Electrical Code 2023 (NEC / NFPA 70)
  // ------------------------------------------------------------------
  {
    corpusKey: "NEC:2023",
    jurisdictionKey: "baseline",
    codeName: "National Electrical Code 2023 (NFPA 70)",
    codeYear: "2023",
    part: null,
    tocUrl: "https://up.codes/viewer/florida/nec-2023",
    officialPdfUrl: null,
    sectionUrlPattern: /up\.codes\/viewer\/florida\/nec-2023\/[a-z0-9-]+/i,
    chaptersToInclude: [
      "chapter-1",   // General (Art. 90–110)
      "chapter-2",   // Wiring and Protection (Art. 200–285; incl. 230.42 service)
      "chapter-3",   // Wiring Methods and Materials
      "chapter-4",   // Equipment for General Use
      "chapter-7",   // Special Conditions (Art. 700–770 emergency/standby)
    ],
    estimatedChunks: 150,
  },

  // ------------------------------------------------------------------
  // International Plumbing Code 2021 (IPC) — Table 403.1 fixture counts
  // ------------------------------------------------------------------
  {
    corpusKey: "IPC:2021",
    jurisdictionKey: "baseline",
    codeName: "International Plumbing Code 2021",
    codeYear: "2021",
    part: null,
    tocUrl: "https://up.codes/viewer/florida/ipc-2021",
    officialPdfUrl: null,
    sectionUrlPattern: /up\.codes\/viewer\/florida\/ipc-2021\/[a-z0-9-]+/i,
    chaptersToInclude: [
      "chapter-1",  "chapter-2",  "chapter-3",  "chapter-4",
      "chapter-5",  "chapter-6",  "chapter-7",  "chapter-8",
      "chapter-9",  "chapter-10", "chapter-11",
    ],
    estimatedChunks: 100,
    note: "CA uses UPC instead — IPC chunks are skipped automatically for CA projects when corpus search prioritizes state-key matches.",
  },

  // ------------------------------------------------------------------
  // International Mechanical Code 2021 (IMC) — Table 403.3 ventilation
  // ------------------------------------------------------------------
  {
    corpusKey: "IMC:2021",
    jurisdictionKey: "baseline",
    codeName: "International Mechanical Code 2021",
    codeYear: "2021",
    part: null,
    tocUrl: "https://up.codes/viewer/florida/imc-2021",
    officialPdfUrl: null,
    sectionUrlPattern: /up\.codes\/viewer\/florida\/imc-2021\/[a-z0-9-]+/i,
    chaptersToInclude: [
      "chapter-1", "chapter-2", "chapter-3", "chapter-4",
      "chapter-5", "chapter-6", "chapter-7", "chapter-8", "chapter-9",
    ],
    estimatedChunks: 80,
  },

  // ------------------------------------------------------------------
  // International Energy Conservation Code 2021 (IECC)
  // ------------------------------------------------------------------
  {
    corpusKey: "IECC:2021",
    jurisdictionKey: "baseline",
    codeName: "International Energy Conservation Code 2021",
    codeYear: "2021",
    part: null,
    tocUrl: "https://up.codes/viewer/florida/iecc-2021",
    officialPdfUrl: null,
    sectionUrlPattern: /up\.codes\/viewer\/florida\/iecc-2021\/[a-z0-9-]+/i,
    chaptersToInclude: [
      "commercial-energy-efficiency",
      "residential-energy-efficiency",
      "chapter-c1", "chapter-c2", "chapter-c3", "chapter-c4", "chapter-c5",
      "chapter-r1", "chapter-r2", "chapter-r3", "chapter-r4",
    ],
    estimatedChunks: 60,
  },

  // ------------------------------------------------------------------
  // NFPA 13 — Sprinkler Systems (2022)
  // ------------------------------------------------------------------
  {
    corpusKey: "NFPA13:2022",
    jurisdictionKey: "baseline",
    codeName: "NFPA 13 — Standard for the Installation of Sprinkler Systems (2022)",
    codeYear: "2022",
    part: null,
    tocUrl: "https://up.codes/viewer/florida/nfpa-13-2022",
    officialPdfUrl: null,
    sectionUrlPattern: /up\.codes\/viewer\/florida\/nfpa-13-2022\/[a-z0-9-]+/i,
    estimatedChunks: 80,
    note: "NFPA standards may require session cookie for full-text view. If up.codes ingest fails, fall back to NFPA free-access viewer.",
  },

  // ------------------------------------------------------------------
  // NFPA 72 — National Fire Alarm and Signaling Code (2022)
  // ------------------------------------------------------------------
  {
    corpusKey: "NFPA72:2022",
    jurisdictionKey: "baseline",
    codeName: "NFPA 72 — National Fire Alarm and Signaling Code (2022)",
    codeYear: "2022",
    part: null,
    tocUrl: "https://up.codes/viewer/florida/nfpa-72-2022",
    officialPdfUrl: null,
    sectionUrlPattern: /up\.codes\/viewer\/florida\/nfpa-72-2022\/[a-z0-9-]+/i,
    estimatedChunks: 80,
  },

  // ------------------------------------------------------------------
  // ADA 2010 Standards for Accessible Design — federal, public domain
  // jurisdictionKey "federal" — always searched alongside state/baseline.
  // ------------------------------------------------------------------
  {
    corpusKey: "ADA:2010",
    jurisdictionKey: "federal",
    codeName: "ADA Standards for Accessible Design (2010)",
    codeYear: "2010",
    part: null,
    tocUrl: "https://www.access-board.gov/ada/",
    officialPdfUrl: "https://www.ada.gov/assets/_pdfs/2010ADAstandards.pdf",
    sectionUrlPattern: /access-board\.gov\/ada\/[a-z0-9-]+/i,
    estimatedChunks: 120,
    note: "Public domain — no licensing constraint. Applies to every commercial project regardless of state. Chapters 2 (scoping), 4 (accessible routes), 6 (plumbing elements), 7 (signs), and Table 208.2 (parking counts) drive ADA-* rules.",
  },
];

// =====================================================================
// All sources — union of CA base + national/federal
// =====================================================================
export const ALL_CODE_SOURCES: CodeSource[] = [
  ...CA_BASE_CODE_SOURCES,
  ...NATIONAL_CODE_SOURCES,
];

// =====================================================================
// Helper: get total estimated chunk count
// =====================================================================
export function totalEstimatedChunks(): number {
  return ALL_CODE_SOURCES.reduce((s, src) => s + src.estimatedChunks, 0);
}

export function getSource(corpusKey: string): CodeSource | null {
  return ALL_CODE_SOURCES.find(s => s.corpusKey === corpusKey) ?? null;
}
