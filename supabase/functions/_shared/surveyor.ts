// =====================================================================
// Jurisdiction Surveyor.
//
// Resolves a JurisdictionProfile for a specific submittal:
//   - Which code sources (Municode, eCode360, direct .gov) apply
//   - Which IBC/CBC year the jurisdiction is on
//   - What WUI zone (if any) the project address falls in
//
// This is the piece that makes the Researcher jurisdiction-aware.
// Without the Surveyor, every research session does a generic web
// search and the LLM has to figure out which source to trust.
// With the Surveyor, a Los Angeles plan check hits LAMC on Municode
// first — a Pasadena source never appears in a San Jose session.
//
// The Surveyor is deterministic (no LLM). It reads from:
//   1. The hardcoded JURISDICTION_REGISTRY below (for known cities)
//   2. The Municode and eCode360 scraper registries
//   3. CalFire FHSZ GIS (for CA addresses, async)
//
// For unrecognized jurisdiction keys the Surveyor still returns a
// usable profile with generic IBC sources — the Researcher can
// always fall back to a broad web search.
//
// Usage (in process-submittal/index.ts):
//   const profile = await surveyJurisdiction("CA:LOS_ANGELES", projectAddress, supabase);
//   report = await runTriage(llm, ctx, agency, planText, {
//     useLlm: true,
//     research: { supabase, jurisdictionProfile: profile, maxCitations: 5 },
//   });
// =====================================================================

import { SupabaseClient } from "https://esm.sh/@supabase/supabase-js@2.45.0";
import {
  MUNICODE_CA_REGISTRY, MunicodeEntry,
  buildMunicodeBaseUrl, searchQueryForMunicode,
} from "./scrapers/municode.ts";
import {
  ECODE360_REGISTRY, ECode360Entry,
  buildECode360BaseUrl, searchQueryForECode360,
} from "./scrapers/ecode360.ts";
import { WuiZoneResult } from "./wui.ts";
import {
  PropertyProfile,
  resolvePropertyProfile,
  renderPropertyProfileForResearcher,
} from "./property.ts";

// =====================================================================
// Types
// =====================================================================

export type SourceKind =
  | "municode"
  | "ecode360"
  | "amlegal"
  | "codepublishing"
  | "direct_gov"
  | "icc_ibc"
  | "state_code";

export interface CodeSource {
  kind: SourceKind;
  label: string;            // display name, e.g. "Los Angeles Municipal Code"
  baseUrl: string;          // starting URL for the researcher to fetch
  searchSiteHint: string;   // prepended to web search query, e.g. "site:library.municode.com/ca/los_angeles"
  ibcYear?: string;         // IBC/CBC year this source reflects
  // If set, the researcher appends this note to its system context
  note?: string;
}

export interface JurisdictionProfile {
  jurisdictionKey: string;
  state: string | null;
  ibcYear: string;           // dominant IBC year for this jurisdiction
  // Ordered list of code sources — most specific first.
  // The researcher tries these before falling back to generic web search.
  sources: CodeSource[];
  // WUI zone (CA only; null if non-CA or geocode failed).
  // Convenience alias for propertyProfile.wui_zone.
  wuiZone: WuiZoneResult | null;
  // Full property overlay profile: flood zone, coastal zone, parcel, LADBS.
  // Populated when a projectAddress was provided to surveyJurisdiction().
  propertyProfile?: PropertyProfile;
  resolvedAt: string;
}

// =====================================================================
// Hardcoded jurisdiction registry
// Covers jurisdictions that need special source routing beyond what
// the Municode / eCode360 registries provide.
// =====================================================================

interface JurisdictionEntry {
  state: string;
  ibcYear: string;
  extraSources?: Omit<CodeSource, "searchSiteHint">[];
  isCalFire?: boolean;  // true = CA jurisdiction, trigger WUI lookup
}

const JURISDICTION_REGISTRY: Record<string, JurisdictionEntry> = {

  // ------------------------------------------------------------------
  // California — CBC cycle (not directly IBC; IBC-based)
  // ------------------------------------------------------------------
  "CA:LOS_ANGELES":    { state: "CA", ibcYear: "2022", isCalFire: true },
  "CA:SAN_DIEGO":      { state: "CA", ibcYear: "2022", isCalFire: true },
  "CA:SAN_FRANCISCO":  { state: "CA", ibcYear: "2022", isCalFire: true },
  "CA:SAN_JOSE":       { state: "CA", ibcYear: "2022", isCalFire: true },
  "CA:FRESNO":         { state: "CA", ibcYear: "2022", isCalFire: true },
  "CA:SACRAMENTO":     { state: "CA", ibcYear: "2022", isCalFire: true },
  "CA:LONG_BEACH":     { state: "CA", ibcYear: "2022", isCalFire: true },
  "CA:OAKLAND":        { state: "CA", ibcYear: "2022", isCalFire: true },
  "CA:BAKERSFIELD":    { state: "CA", ibcYear: "2022", isCalFire: true },
  "CA:ANAHEIM":        { state: "CA", ibcYear: "2022", isCalFire: true },
  "CA:RIVERSIDE":      { state: "CA", ibcYear: "2022", isCalFire: true },
  "CA:PASADENA":       { state: "CA", ibcYear: "2022", isCalFire: true },

  // amlegal-hosted CA cities (different retrieval path from Municode)
  "CA:SAN_BERNARDINO": { state: "CA", ibcYear: "2022", isCalFire: true,
    extraSources: [{
      kind: "amlegal",
      label: "San Bernardino Municipal Code (American Legal)",
      baseUrl: "https://codelibrary.amlegal.com/codes/sanbernardinoofca/latest/overview",
      ibcYear: "2022",
    }],
  },
  "CA:STOCKTON": { state: "CA", ibcYear: "2022", isCalFire: true,
    extraSources: [{
      kind: "amlegal",
      label: "Stockton Municipal Code (American Legal)",
      baseUrl: "https://codelibrary.amlegal.com/codes/stockton/latest/overview",
      ibcYear: "2022",
    }],
  },

  // ------------------------------------------------------------------
  // Washington State (existing WA targets from early build)
  // ------------------------------------------------------------------
  "WA":          { state: "WA", ibcYear: "2021" },
  "WA:SEATTLE":  { state: "WA", ibcYear: "2021",
    extraSources: [{
      kind: "direct_gov",
      label: "Seattle Building Code (Seattle.gov)",
      baseUrl: "https://www.seattle.gov/sdci/codes/codes-we-enforce-(a-z)/seattle-building-code",
      ibcYear: "2021",
    }],
  },
  "WA:TACOMA":   { state: "WA", ibcYear: "2021",
    extraSources: [{
      kind: "codepublishing",
      label: "Tacoma Municipal Code (CodePublishing.com)",
      baseUrl: "https://www.codepublishing.com/WA/Tacoma",
      ibcYear: "2021",
    }],
  },
  "WA:SPOKANE":  { state: "WA", ibcYear: "2021" },

  // ------------------------------------------------------------------
  // New Jersey — NJ UCC (IBC-based)
  // ------------------------------------------------------------------
  "NJ:HOBOKEN":      { state: "NJ", ibcYear: "2018" },
  "NJ:PRINCETON":    { state: "NJ", ibcYear: "2018" },
  "NJ:MONTCLAIR":    { state: "NJ", ibcYear: "2018" },
  "NJ:JERSEY_CITY":  { state: "NJ", ibcYear: "2018" },
  "NJ:NEWARK":       { state: "NJ", ibcYear: "2018" },

  // ------------------------------------------------------------------
  // New York — NY State Building Code (2020 IBC-based)
  // ------------------------------------------------------------------
  "NY:YONKERS":      { state: "NY", ibcYear: "2020" },
  "NY:WHITE_PLAINS": { state: "NY", ibcYear: "2020" },
  "NY:NEW_ROCHELLE": { state: "NY", ibcYear: "2020" },

  // ------------------------------------------------------------------
  // Connecticut — CT State Building Code (2018 IBC-based)
  // ------------------------------------------------------------------
  "CT:STAMFORD":  { state: "CT", ibcYear: "2018" },
  "CT:GREENWICH": { state: "CT", ibcYear: "2018" },
  "CT:NORWALK":   { state: "CT", ibcYear: "2018" },

  // ------------------------------------------------------------------
  // Maryland, Virginia, Pennsylvania
  // ------------------------------------------------------------------
  "MD:MONTGOMERY_COUNTY": { state: "MD", ibcYear: "2018" },
  "MD:HOWARD_COUNTY":     { state: "MD", ibcYear: "2018" },
  "VA:FAIRFAX_COUNTY":    { state: "VA", ibcYear: "2018" },
  "PA:LOWER_MERION":      { state: "PA", ibcYear: "2018" },
  "PA:MONTGOMERY_COUNTY": { state: "PA", ibcYear: "2018" },

  // ------------------------------------------------------------------
  // Generic state-level baselines (used when city is unknown)
  // ------------------------------------------------------------------
  "CA":  { state: "CA", ibcYear: "2022", isCalFire: true },
  "WA":  { state: "WA", ibcYear: "2021" },
  "NY":  { state: "NY", ibcYear: "2020" },
  "NJ":  { state: "NJ", ibcYear: "2018" },
  "TX":  { state: "TX", ibcYear: "2021" },
  "FL":  { state: "FL", ibcYear: "2020" },
  "IL":  { state: "IL", ibcYear: "2021" },
  "baseline": { state: null, ibcYear: "2021" },
};

// =====================================================================
// IBC baseline source (always last in the source list)
// NOTE: IBC verbatim text is ICC copyright; see docs/ICC_LICENSING.md.
// The researcher cites section numbers + summaries, not full IBC text.
// =====================================================================
const IBC_BASELINE_SOURCE: CodeSource = {
  kind: "icc_ibc",
  label: "IBC 2021 (ICC — baseline)",
  baseUrl: "https://up.codes/viewer/general/ibc-2021",
  searchSiteHint: "site:up.codes/viewer",
  note: "IBC verbatim text is ICC copyrighted. Cite section number and a plain-language summary of the requirement rather than quoting full text. For official verbatim text, an ICC digital license is required (see docs/ICC_LICENSING.md).",
};

const STATE_CODE_SOURCES: Record<string, CodeSource> = {
  CA: {
    kind: "state_code",
    label: "California Building Code (2022 CBC / Title 24)",
    baseUrl: "https://up.codes/viewer/california/ca-building-code-2022",
    searchSiteHint: "site:up.codes/viewer/california",
    ibcYear: "2022",
    note: "California adopts IBC as CBC Title 24 on its own 3-year cycle with local amendments. Always prefer CBC over raw IBC for CA projects.",
  },
  WA: {
    kind: "state_code",
    label: "Washington State Building Code (2021 WSBC)",
    baseUrl: "https://up.codes/viewer/washington/wa-building-code-2021",
    searchSiteHint: "site:up.codes/viewer/washington",
    ibcYear: "2021",
  },
  NY: {
    kind: "state_code",
    label: "New York State Building Code (2020 NYSBC)",
    baseUrl: "https://up.codes/viewer/new-york/ny-building-code-2020",
    searchSiteHint: "site:up.codes/viewer/new-york",
    ibcYear: "2020",
  },
  NJ: {
    kind: "state_code",
    label: "New Jersey Uniform Construction Code (NJ UCC)",
    baseUrl: "https://www.nj.gov/dca/divisions/codes/publications/codes.html",
    searchSiteHint: "site:nj.gov/dca",
    ibcYear: "2018",
  },
  CT: {
    kind: "state_code",
    label: "Connecticut State Building Code",
    baseUrl: "https://portal.ct.gov/DCS/Building-Department/Building-Codes",
    searchSiteHint: "site:portal.ct.gov DCS building code",
    ibcYear: "2018",
  },
  PA: {
    kind: "state_code",
    label: "Pennsylvania Uniform Construction Code (PA UCC)",
    baseUrl: "https://www.dli.pa.gov/ucc/Pages/UCC.aspx",
    searchSiteHint: "site:dli.pa.gov ucc",
    ibcYear: "2018",
  },
  MD: {
    kind: "state_code",
    label: "Maryland Building Performance Standards",
    baseUrl: "https://www.dllr.state.md.us/comar/subtitle_chapters/10_Chapters.aspx",
    searchSiteHint: "site:dllr.state.md.us",
    ibcYear: "2018",
  },
  VA: {
    kind: "state_code",
    label: "Virginia Uniform Statewide Building Code (USBC)",
    baseUrl: "https://up.codes/viewer/virginia/va-building-code-2018",
    searchSiteHint: "site:up.codes/viewer/virginia",
    ibcYear: "2018",
  },
  TX: {
    kind: "state_code",
    label: "Texas Amendments to the IBC 2021",
    baseUrl: "https://www.tdlr.texas.gov/building-codes/",
    searchSiteHint: "site:tdlr.texas.gov",
    ibcYear: "2021",
  },
  FL: {
    kind: "state_code",
    label: "Florida Building Code (FBC 2020, IBC-based)",
    baseUrl: "https://floridabuilding.org/bc/bc_default.aspx",
    searchSiteHint: "site:floridabuilding.org",
    ibcYear: "2020",
  },
};

// =====================================================================
// Build the CodeSource for a Municode entry
// =====================================================================
function sourcesFromMunicode(entry: MunicodeEntry, jurKey: string): CodeSource[] {
  const sources: CodeSource[] = [];
  const codePriority: (keyof MunicodeEntry["codes"])[] = ["building", "municipal", "zoning"];
  for (const codeType of codePriority) {
    const code = entry.codes[codeType];
    if (!code) continue;
    sources.push({
      kind: "municode",
      label: code.label,
      baseUrl: buildMunicodeBaseUrl(entry, codeType),
      searchSiteHint: `site:library.municode.com/ca/${entry.clientPath}`,
      ibcYear: entry.ibcYear,
      note: entry.notes,
    });
  }
  return sources;
}

// =====================================================================
// Build the CodeSource for an eCode360 entry
// =====================================================================
function sourceFromECode360(entry: ECode360Entry): CodeSource {
  return {
    kind: "ecode360",
    label: entry.codeTitle,
    baseUrl: buildECode360BaseUrl(entry),
    searchSiteHint: `site:ecode360.com/${entry.codeId}`,
    ibcYear: entry.ibcYear,
    note: entry.notes,
  };
}

// =====================================================================
// Public: surveyJurisdiction
// =====================================================================

/**
 * Build a JurisdictionProfile for a specific submittal.
 *
 * @param jurisdictionKey  From agencies.jurisdiction_key, e.g. "CA:LOS_ANGELES"
 * @param projectAddress   Full project address (for WUI GIS lookup). Optional.
 * @param supabase         Optional — enables WUI zone caching.
 */
export async function surveyJurisdiction(
  jurisdictionKey: string,
  projectAddress?: string | null,
  supabase?: SupabaseClient,
): Promise<JurisdictionProfile> {
  const entry = JURISDICTION_REGISTRY[jurisdictionKey]
    ?? JURISDICTION_REGISTRY[jurisdictionKey.split(":")[0]]  // try state-level fallback
    ?? JURISDICTION_REGISTRY["baseline"];

  const state = entry.state;
  const ibcYear = entry.ibcYear ?? "2021";

  // -------- 1. Assemble ordered code sources -------------------------
  const sources: CodeSource[] = [];

  // (a) Municipality-specific sources from Municode registry
  const municodeEntry: MunicodeEntry | null = MUNICODE_CA_REGISTRY[jurisdictionKey] ?? null;
  if (municodeEntry) {
    sources.push(...sourcesFromMunicode(municodeEntry, jurisdictionKey));
  }

  // (b) Municipality-specific sources from eCode360 registry
  const eCode360Entry: ECode360Entry | null = ECODE360_REGISTRY[jurisdictionKey] ?? null;
  if (eCode360Entry) {
    sources.push(sourceFromECode360(eCode360Entry));
  }

  // (c) Extra sources hardcoded per jurisdiction (amlegal, direct_gov, codepublishing)
  for (const extra of entry.extraSources ?? []) {
    sources.push({
      ...extra,
      searchSiteHint: extra.baseUrl ? `site:${new URL(extra.baseUrl).hostname}` : "",
    });
  }

  // (d) State-level code
  if (state && STATE_CODE_SOURCES[state]) {
    sources.push(STATE_CODE_SOURCES[state]);
  }

  // (e) IBC baseline — always last
  sources.push({ ...IBC_BASELINE_SOURCE, ibcYear });

  // -------- 2. Property profile (async GIS fan-out) ------------------
  // For any address we resolve the full PropertyProfile: FEMA flood zone
  // is nationwide; CA-specific lookups (WUI, Coastal, LA parcel/LADBS)
  // are gated inside resolvePropertyProfile on the address text itself.
  let wuiZone: WuiZoneResult | null = null;
  let propertyProfile: PropertyProfile | undefined;
  if (projectAddress) {
    try {
      propertyProfile = await resolvePropertyProfile(projectAddress, supabase);
      wuiZone = propertyProfile.wui_zone ?? null;
    } catch (err) {
      console.warn("[surveyor] property profile failed:", err);
    }
  }

  return {
    jurisdictionKey,
    state,
    ibcYear,
    sources,
    wuiZone,
    propertyProfile,
    resolvedAt: new Date().toISOString(),
  };
}

// =====================================================================
// Utility: render the profile as context text for the researcher prompt
// =====================================================================

/**
 * Render a JurisdictionProfile into a concise text block suitable for
 * injection into the researcher's system or user message.
 *
 * Example output:
 *   Jurisdiction profile for CA:LOS_ANGELES (CBC 2022):
 *   1. Los Angeles Municipal Code (Municode): https://library.municode.com/ca/los_angeles/codes/code_of_ordinances
 *      Search hint: site:library.municode.com/ca/los_angeles
 *   2. California Building Code (2022 CBC / Title 24): https://up.codes/viewer/california/ca-building-code-2022
 *      Search hint: site:up.codes/viewer/california
 *      Note: Always prefer CBC over raw IBC for CA projects.
 *   3. IBC 2021 (baseline): https://up.codes/viewer/general/ibc-2021
 *      NOTE: IBC text is ICC copyrighted. Summarize, do not quote verbatim.
 *   WUI: High FHSZ (SRA) in Los Angeles County. CBC Chapter 7A applies.
 */
export function renderProfileForResearcher(profile: JurisdictionProfile): string {
  const lines: string[] = [
    `Jurisdiction profile for ${profile.jurisdictionKey} (IBC/CBC ${profile.ibcYear}):`,
    `Use the following sources in order (most specific first):`,
  ];

  profile.sources.forEach((s, i) => {
    lines.push(`${i + 1}. ${s.label}: ${s.baseUrl}`);
    lines.push(`   Search hint: ${s.searchSiteHint}`);
    if (s.note) lines.push(`   NOTE: ${s.note}`);
  });

  if (profile.wuiZone) {
    const { in_wui, haz_class, sra_type, county } = profile.wuiZone;
    if (in_wui && haz_class) {
      const sraLabel = sra_type ? ` (${sra_type})` : "";
      const countyLabel = county ? ` in ${county} County` : "";
      lines.push(
        `WUI ZONE: ${haz_class} FHSZ${sraLabel}${countyLabel}. ` +
        `CBC Chapter 7A wildfire-resistive construction requirements apply to this project.`,
      );
    } else {
      lines.push(`WUI ZONE: No CalFire FHSZ designation at this address. CBC Chapter 7A not triggered by location.`);
    }
  }

  if (profile.propertyProfile) {
    const overlayText = renderPropertyProfileForResearcher(profile.propertyProfile);
    if (overlayText) lines.push("", overlayText);
  }

  return lines.join("\n");
}
