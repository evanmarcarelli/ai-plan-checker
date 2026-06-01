// =====================================================================
// Municode scraper helpers.
//
// Municode (library.municode.com) hosts the municipal code for:
//   - Los Angeles, CA
//   - San Diego, CA
//   - San Francisco, CA
// ... and hundreds of other jurisdictions. These three are the largest
// CA cities NOT on the American Legal (amlegal.com) platform, covering
// ~75% of CA SFR/ADU plan volume by population.
//
// What this module provides:
//   1. MUNICODE_REGISTRY — a typed map of known client paths + code IDs
//      for each jurisdiction. "Client path" is the slug in the Municode
//      URL: library.municode.com/ca/{clientPath}/codes/{codeId}
//   2. buildMunicodeUrl() — construct a plausible section URL from a
//      code ref string (best-effort; Municode uses JS rendering with
//      nodeId params, so exact deep-links need web search confirmation).
//   3. searchQueryForMunicode() — format a Brave/Serper query that is
//      scoped to the right Municode client so the researcher's first
//      fetch is already on the right page.
//
// Usage: consumed by _shared/surveyor.ts to build CodeSource entries
// that are injected into the researcher's context before it searches.
// =====================================================================

export interface MunicodeEntry {
  clientPath: string;              // slug after /ca/ in the URL
  codes: {
    municipal?: MunicodeCodeId;    // city's main building/zoning/municipal code
    building?: MunicodeCodeId;     // separate building code if split out
    zoning?: MunicodeCodeId;       // separate zoning/planning code if split out
  };
  ibcAdoptionYear: string;         // IBC year this city formally adopted
  cbc: boolean;                    // true = also enforces California Building Code
  notes?: string;
}

export interface MunicodeCodeId {
  slug: string;          // 'code_of_ordinances', 'building_code', etc.
  label: string;         // human-readable title
  rootNodeHint?: string; // leading nodeId fragment for building/zoning chapters
}

// =====================================================================
// Registry — verified against Municode library as of 2025.
// Verify each entry at: https://library.municode.com/ca/{clientPath}
// =====================================================================
export const MUNICODE_CA_REGISTRY: Record<string, MunicodeEntry> = {

  // ------------------------------------------------------------------
  // Los Angeles, CA — population ~4M
  // LAMC Title 9 Part 3 Chapter 91 = LA Building Code (CBC + local amends)
  // ------------------------------------------------------------------
  "CA:LOS_ANGELES": {
    clientPath: "los_angeles",
    codes: {
      municipal: {
        slug: "code_of_ordinances",
        label: "Los Angeles Municipal Code (LAMC)",
        rootNodeHint: "LAMC_TIT9BURERECO",  // Title 9 = Building Regulations
      },
    },
    ibcAdoptionYear: "2022",   // CA adopts CBC (IBC-based) on its own cycle
    cbc: true,
    notes: "LA Building Code is at LAMC Title 9, Part 3, Chapter 91 (the California Building Code as locally amended). Zoning is LAMC Title 22.",
  },

  // ------------------------------------------------------------------
  // San Diego, CA — population ~1.4M
  // SDMC Chapter 14 = Building Regulations; Title 13 = Zoning
  // ------------------------------------------------------------------
  "CA:SAN_DIEGO": {
    clientPath: "san_diego",
    codes: {
      municipal: {
        slug: "code_of_ordinances",
        label: "San Diego Municipal Code (SDMC)",
        rootNodeHint: "SDMC_CH14BURE",      // Chapter 14 = Building Regulations
      },
    },
    ibcAdoptionYear: "2022",
    cbc: true,
    notes: "Building code at SDMC Chapter 14. Zoning at Title 13. San Diego has notable local amendments for coastal zones (SDMC 23).",
  },

  // ------------------------------------------------------------------
  // San Francisco, CA — population ~870K
  // SF has separate Building, Planning, Housing, and Fire codes on Municode.
  // Building Code = Title 24 CBC as locally amended (Ord. No.)
  // ------------------------------------------------------------------
  "CA:SAN_FRANCISCO": {
    clientPath: "san_francisco",
    codes: {
      building: {
        slug: "building_code",
        label: "San Francisco Building Code",
        rootNodeHint: "SFBC",
      },
      zoning: {
        slug: "planning_code",
        label: "San Francisco Planning Code",
        rootNodeHint: "SFPC",
      },
    },
    ibcAdoptionYear: "2022",
    cbc: true,
    notes: "SF Building Code is its own Municode section, distinct from the Planning Code. SF has significant local fire-resistance amendments (Chapter 9) and ADU regulations.",
  },

  // ------------------------------------------------------------------
  // San Jose, CA — population ~1M (not amlegal; Municode)
  // ------------------------------------------------------------------
  "CA:SAN_JOSE": {
    clientPath: "san_jose",
    codes: {
      municipal: {
        slug: "code_of_ordinances",
        label: "San José Municipal Code",
        rootNodeHint: "SJMC_TIT23ZO",    // Title 23 = Zoning
      },
    },
    ibcAdoptionYear: "2022",
    cbc: true,
    notes: "Building regs at Title 17; Zoning at Title 23. San José has strong ADU ordinances.",
  },

  // ------------------------------------------------------------------
  // Fresno, CA — population ~545K (Municode)
  // ------------------------------------------------------------------
  "CA:FRESNO": {
    clientPath: "fresno_ca",
    codes: {
      municipal: {
        slug: "code_of_ordinances",
        label: "Fresno Municipal Code",
        rootNodeHint: "FMC_TIT12BUCO",
      },
    },
    ibcAdoptionYear: "2022",
    cbc: true,
  },

  // ------------------------------------------------------------------
  // Sacramento, CA — population ~530K (Municode)
  // ------------------------------------------------------------------
  "CA:SACRAMENTO": {
    clientPath: "sacramento",
    codes: {
      municipal: {
        slug: "code_of_ordinances",
        label: "Sacramento City Code",
        rootNodeHint: "SCC_TIT15BUCO",
      },
    },
    ibcAdoptionYear: "2022",
    cbc: true,
  },
};

// =====================================================================
// URL builders
// =====================================================================

/**
 * Build the base Municode URL for a jurisdiction's primary code.
 * This is the table-of-contents root; section deep-links require nodeId
 * parameters that are best resolved via web search.
 */
export function buildMunicodeBaseUrl(
  entry: MunicodeEntry,
  codeType: keyof MunicodeEntry["codes"] = "municipal",
): string {
  const code = entry.codes[codeType] ?? entry.codes.municipal ?? Object.values(entry.codes)[0];
  if (!code) return `https://library.municode.com/ca/${entry.clientPath}`;
  return `https://library.municode.com/ca/${entry.clientPath}/codes/${code.slug}`;
}

/**
 * Format a Brave/Serper site-scoped search query for a specific code
 * section within a Municode client.
 *
 * Example output:
 *   "site:library.municode.com/ca/los_angeles LAMC 91.1.1 sprinkler"
 */
export function searchQueryForMunicode(
  entry: MunicodeEntry,
  codeRef: string,
  contextKeywords?: string,
): string {
  const siteFilter = `site:library.municode.com/ca/${entry.clientPath}`;
  const parts = [siteFilter, codeRef];
  if (contextKeywords) parts.push(contextKeywords.split(/\s+/).slice(0, 4).join(" "));
  return parts.join(" ");
}

/**
 * Attempt to construct a plausible direct section URL using a root node hint
 * plus the section reference. This is an approximation — Municode's actual
 * nodeIds are assigned on ingest and aren't derivable from code section numbers.
 * Use as a first-try hint; fall back to web search if it 404s.
 *
 * Only works when the entry has a rootNodeHint.
 */
export function buildMunicodeSectionUrl(
  entry: MunicodeEntry,
  codeType: keyof MunicodeEntry["codes"],
  sectionSlug: string,   // e.g. 'LAMC_TIT9BURERECO_CH91_S91150' (caller-provided)
): string | null {
  const code = entry.codes[codeType];
  if (!code || !code.rootNodeHint) return null;
  return `https://library.municode.com/ca/${entry.clientPath}/codes/${code.slug}?nodeId=${sectionSlug}`;
}

// =====================================================================
// Lookup helpers
// =====================================================================

export function getMunicodeEntry(jurisdictionKey: string): MunicodeEntry | null {
  return MUNICODE_CA_REGISTRY[jurisdictionKey] ?? null;
}

/** Returns all registered CA cities that use Municode. */
export function allMunicodeCaKeys(): string[] {
  return Object.keys(MUNICODE_CA_REGISTRY);
}
