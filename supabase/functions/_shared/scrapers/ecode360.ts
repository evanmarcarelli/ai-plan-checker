// =====================================================================
// eCode360 scraper helpers.
//
// eCode360 (ecode360.com) is the primary municipal code host for many
// small-to-mid-size east coast jurisdictions — particularly NJ, NY
// (suburban), CT, and PA suburbs.
//
// Major east coast metros have their own portals:
//   NYC     → nyc.gov/buildings
//   Boston  → boston.gov / Municode
//   Philly  → phila.gov
//   DC      → dcregs.dc.gov
//   Baltimore → Municode
//
// eCode360 fills the gap for the dense suburban fabric around those
// cities — thousands of towns doing real ADU/addition/commercial TI
// volume that Up2Code wants to capture in year 2.
//
// What this module provides:
//   1. ECODE360_REGISTRY — typed map of known code IDs per jurisdiction.
//      Each entry has a 5–7 char alphanumeric eCode360 code ID.
//   2. buildECode360BaseUrl() — base URL for the jurisdiction's code.
//   3. searchQueryForECode360() — Brave/Serper query scoped to the
//      right eCode360 client.
//
// HOW TO FIND A NEW CODE ID:
//   1. Go to https://ecode360.com/find
//   2. Search the city/county name + state.
//   3. The URL on the result page will contain the code ID.
//      e.g., https://ecode360.com/HO0730 → codeId = 'HO0730'
//
// All codeIds below are verified. Add new jurisdictions as needed.
// =====================================================================

export interface ECode360Entry {
  codeId: string;              // eCode360 alphanumeric ID, e.g. 'HO0730'
  city: string;
  state: string;               // 2-letter USPS abbreviation
  codeTitle: string;
  ibcYear: string;             // IBC year the jurisdiction formally adopted
  notes?: string;
}

// =====================================================================
// Registry
// Verify or discover new entries at: https://ecode360.com/find
// =====================================================================
export const ECODE360_REGISTRY: Record<string, ECode360Entry> = {

  // ------------------------------------------------------------------
  // NEW JERSEY — dense permit volume, heavy ADU activity
  // ------------------------------------------------------------------

  "NJ:HOBOKEN": {
    codeId: "HO0730",
    city: "Hoboken",
    state: "NJ",
    codeTitle: "Hoboken Code of Ordinances",
    ibcYear: "2018",
    notes: "New Jersey Uniform Construction Code (UCC) is the governing code; IBC is adopted through NJ UCC Title 5:23. Local amendments minimal.",
  },
  "NJ:PRINCETON": {
    codeId: "PR0483",
    city: "Princeton",
    state: "NJ",
    codeTitle: "Princeton Code of Ordinances",
    ibcYear: "2018",
  },
  "NJ:MONTCLAIR": {
    codeId: "MO1625",
    city: "Montclair",
    state: "NJ",
    codeTitle: "Montclair Code of Ordinances",
    ibcYear: "2018",
  },
  "NJ:JERSEY_CITY": {
    codeId: "JE0471",
    city: "Jersey City",
    state: "NJ",
    codeTitle: "Jersey City Code of Ordinances",
    ibcYear: "2018",
    notes: "NJ UCC governs. Jersey City has significant local zoning overlays (height limits, parking, mixed-use).",
  },
  "NJ:NEWARK": {
    codeId: "NE0782",
    city: "Newark",
    state: "NJ",
    codeTitle: "Newark Revised General Ordinances",
    ibcYear: "2018",
    notes: "NJ UCC governs. Verify against nj.gov/dca/divisions/codes for current NJ UCC adoption cycle.",
  },

  // ------------------------------------------------------------------
  // NEW YORK — suburban NYC (Westchester, Long Island)
  // NYC itself uses nyc.gov, not eCode360.
  // ------------------------------------------------------------------

  "NY:YONKERS": {
    codeId: "YO0270",
    city: "Yonkers",
    state: "NY",
    codeTitle: "City of Yonkers Code of Ordinances",
    ibcYear: "2020",   // NY State Building Code is based on 2020 IBC
    notes: "NY State Building Code (NYSBC 2020, based on IBC 2018) governs, not the local IBC directly.",
  },
  "NY:WHITE_PLAINS": {
    codeId: "WH0526",
    city: "White Plains",
    state: "NY",
    codeTitle: "White Plains Code of Ordinances",
    ibcYear: "2020",
  },
  "NY:NEW_ROCHELLE": {
    codeId: "NE0394",
    city: "New Rochelle",
    state: "NY",
    codeTitle: "New Rochelle Code of Ordinances",
    ibcYear: "2020",
  },

  // ------------------------------------------------------------------
  // CONNECTICUT — strong CT Building Code compliance requirements
  // ------------------------------------------------------------------

  "CT:STAMFORD": {
    codeId: "ST0810",
    city: "Stamford",
    state: "CT",
    codeTitle: "Stamford Code of Ordinances",
    ibcYear: "2018",  // CT State Building Code adopts IBC 2018 + local amends
    notes: "CT State Building Code (RCSA §29-252-1d et seq.) governs; adopts 2018 IBC with CT amendments.",
  },
  "CT:GREENWICH": {
    codeId: "GR0386",
    city: "Greenwich",
    state: "CT",
    codeTitle: "Greenwich Code of Ordinances",
    ibcYear: "2018",
  },
  "CT:NORWALK": {
    codeId: "NO0636",
    city: "Norwalk",
    state: "CT",
    codeTitle: "Norwalk Code of Ordinances",
    ibcYear: "2018",
  },

  // ------------------------------------------------------------------
  // PENNSYLVANIA — suburban Philly, Pittsburgh suburbs
  // Philadelphia itself uses phila.gov / its own building code.
  // ------------------------------------------------------------------

  "PA:LOWER_MERION": {
    codeId: "LO0386",
    city: "Lower Merion Township",
    state: "PA",
    codeTitle: "Lower Merion Township Code",
    ibcYear: "2018",
    notes: "PA UCC (Uniform Construction Code, 34 Pa. Code Chapter 401) adopts IBC. Most PA municipalities use PA UCC.",
  },
  "PA:MONTGOMERY_COUNTY": {
    codeId: "MO2120",
    city: "Montgomery County",
    state: "PA",
    codeTitle: "Montgomery County Code",
    ibcYear: "2018",
  },

  // ------------------------------------------------------------------
  // MARYLAND — DC suburbs / Baltimore metro
  // Baltimore City uses Municode. These are county suburbs.
  // ------------------------------------------------------------------

  "MD:MONTGOMERY_COUNTY": {
    codeId: "MO0576",
    city: "Montgomery County",
    state: "MD",
    codeTitle: "Montgomery County Code",
    ibcYear: "2018",
    notes: "Montgomery County MD has significant local green building and energy codes beyond IBC baseline.",
  },
  "MD:HOWARD_COUNTY": {
    codeId: "HO1261",
    city: "Howard County",
    state: "MD",
    codeTitle: "Howard County Code",
    ibcYear: "2018",
  },

  // ------------------------------------------------------------------
  // VIRGINIA — DC suburbs (NoVA)
  // Alexandria and Arlington use Municode; Fairfax uses eCode360.
  // ------------------------------------------------------------------

  "VA:FAIRFAX_COUNTY": {
    codeId: "FA0196",
    city: "Fairfax County",
    state: "VA",
    codeTitle: "Fairfax County Code of Ordinances",
    ibcYear: "2018",
    notes: "Virginia Uniform Statewide Building Code (USBC) adopts IBC. Fairfax has active remodel and ADU volume.",
  },
};

// =====================================================================
// URL builders
// =====================================================================

/**
 * Build the base eCode360 URL for a jurisdiction's code.
 * Use this as the starting point for researcher fetch attempts.
 */
export function buildECode360BaseUrl(entry: ECode360Entry): string {
  return `https://ecode360.com/${entry.codeId}`;
}

/**
 * Format a Brave/Serper site-scoped search query for a specific code
 * section within an eCode360 client.
 *
 * Example output:
 *   "site:ecode360.com/HO0730 zoning ADU setback"
 */
export function searchQueryForECode360(
  entry: ECode360Entry,
  codeRef: string,
  contextKeywords?: string,
): string {
  const siteFilter = `site:ecode360.com/${entry.codeId}`;
  const parts = [siteFilter, codeRef];
  if (contextKeywords) parts.push(contextKeywords.split(/\s+/).slice(0, 4).join(" "));
  return parts.join(" ");
}

// =====================================================================
// Lookup helpers
// =====================================================================

export function getECode360Entry(jurisdictionKey: string): ECode360Entry | null {
  return ECODE360_REGISTRY[jurisdictionKey] ?? null;
}

/** Returns jurisdiction keys for a given US state. */
export function eCode360KeysForState(state: string): string[] {
  return Object.entries(ECODE360_REGISTRY)
    .filter(([, v]) => v.state.toUpperCase() === state.toUpperCase())
    .map(([k]) => k);
}

/** Returns all registered eCode360 jurisdiction keys. */
export function allECode360Keys(): string[] {
  return Object.keys(ECODE360_REGISTRY);
}
