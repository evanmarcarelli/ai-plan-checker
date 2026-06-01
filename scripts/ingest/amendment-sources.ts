// =====================================================================
// 15-city CA amendment ordinance sources — Session B
//
// Each city adopted the 2022 CBC with local amendments. These local
// amendments are the jurisdiction-specific overrides that matter most
// for plan review — they're what makes "CA:LOS_ANGELES" different from
// "CA:PASADENA" even though both use the 2022 CBC as their base.
//
// SOURCE STRUCTURE
// ----------------
// Each AmendmentSource specifies:
//   - jurisdictionKey: used for code_chunks.jurisdiction_key filtering
//   - adoptionRef: the ordinance that formally adopted the 2022 CBC
//   - municodeClientPath / eCode360Id: where to find the municipal code
//   - keyAmendmentChapters: which sections of the local code to ingest
//     (the building chapter with the CBC amendments, NOT the whole code)
//   - keyAmendmentTopics: known high-value local changes to flag
//
// IMPORTANT: Each city's adoption ordinance typically amends Title 24
// in their municipal code (not the CBC itself). The ingest pipeline
// fetches those sections and tags them with the city's jurisdiction_key.
//
// Estimated ~600 total chunks across 15 cities (~40 chunks per city).
// =====================================================================

export interface AmendmentSource {
  jurisdictionKey: string;       // 'CA:LOS_ANGELES', 'CA:PASADENA', etc.
  cityName: string;
  county: string;
  ibcYear: string;               // base CBC year adopted
  adoptionOrdRef: string;        // ordinance number or reference
  // Primary code host
  host: "municode" | "ecode360" | "amlegal" | "direct_gov";
  municodeClientPath?: string;   // e.g. 'los_angeles'
  amlegalUrl?: string;
  directGovUrl?: string;
  // Chapter/section in the municipal code that contains building amendments
  buildingCodeChapterUrl: string;
  // Specific section numbers or URL fragments to include
  keyAmendmentSections: string[];
  // ADU-specific section URL (high-value for CA plan volume)
  aduSectionUrl?: string;
  // Known high-impact local amendments (for the researcher's context)
  keyAmendmentTopics: string[];
  estimatedChunks: number;
}

export const CA_AMENDMENT_SOURCES: AmendmentSource[] = [

  // ------------------------------------------------------------------
  // 1. LOS ANGELES CITY — population ~4M
  // LAMC Title 9, Part 3, Chapter 91 = LA Building Code
  // LA has the most extensive local amendments of any CA city.
  // ------------------------------------------------------------------
  {
    jurisdictionKey: "CA:LOS_ANGELES",
    cityName: "City of Los Angeles",
    county: "Los Angeles",
    ibcYear: "2022",
    adoptionOrdRef: "LAMC §91.0101 et seq.",
    host: "municode",
    municodeClientPath: "los_angeles",
    buildingCodeChapterUrl:
      "https://library.municode.com/ca/los_angeles/codes/code_of_ordinances?nodeId=LAMC_TIT9BURERECO_PT3BUCO_CH91BUCOCO",
    keyAmendmentSections: ["91.0101", "91.0103", "91.0105", "91.0109", "91.0110"],
    aduSectionUrl:
      "https://library.municode.com/ca/los_angeles/codes/code_of_ordinances?nodeId=LAMC_TIT1GEPR_ART2ADUN",
    keyAmendmentTopics: [
      "Earthquake Hazard Reduction (soft-story retrofit mandate)",
      "Hillside ordinance (grading, retaining walls, fire access)",
      "ADU ordinance (LAMC 12.21-A, reduced setbacks)",
      "LA Fire Prevention Code amendments (LAFD referral triggers)",
      "Green building requirements (LA Green Building Code)",
      "Accessibility (CalDAG + local elevator exceptions)",
    ],
    estimatedChunks: 55,
  },

  // ------------------------------------------------------------------
  // 2. LOS ANGELES COUNTY (unincorporated) — population ~1M unincorp.
  // Many ADU projects are in unincorporated LA County, NOT LA City.
  // County Building Code = CBC 2022 + county amendments (Title 26).
  // ------------------------------------------------------------------
  {
    jurisdictionKey: "CA:LA_COUNTY",
    cityName: "Los Angeles County (unincorporated)",
    county: "Los Angeles",
    ibcYear: "2022",
    adoptionOrdRef: "LA County Code Title 26",
    host: "amlegal",
    amlegalUrl:
      "https://codelibrary.amlegal.com/codes/lacounty/latest/lacocode/0-0-0-1",
    buildingCodeChapterUrl:
      "https://codelibrary.amlegal.com/codes/lacounty/latest/lacocode/0-0-0-1",
    keyAmendmentSections: ["26.02.030", "26.02.060", "26.02.110"],
    keyAmendmentTopics: [
      "Hillside construction (grading and drainage)",
      "Fire hazard severity zone compliance (LA County FHSZ)",
      "ADU provisions (Title 22 zoning + Title 26 building)",
      "Flood control district requirements",
    ],
    estimatedChunks: 40,
  },

  // ------------------------------------------------------------------
  // 3. VENTURA COUNTY (unincorporated) — population ~850K (~325K unincorp.)
  // Code = CBC 2022 + Ventura County Ordinance Code Division VIII.
  // Division VIII is split into chapters numbered in the 8100s.
  // The countywide WUI / Very-High FHSZ exposure is the load-bearing
  // local amendment surface — most plan-review friction lives there.
  //
  // NOTE on section IDs: the ingester only fetches buildingCodeChapterUrl
  // + aduSectionUrl today; keyAmendmentSections is metadata reserved for
  // the researcher's prioritization pass. The IDs below follow Ventura
  // County's published Division VIII chapter scheme but should be
  // spot-checked against Municode before being used as citation anchors.
  // ------------------------------------------------------------------
  {
    jurisdictionKey: "CA:VENTURA_COUNTY",
    cityName: "Ventura County",
    county: "Ventura",
    ibcYear: "2022",
    adoptionOrdRef: "Ventura County Ordinance Code Div. VIII (Ch. 8101 et seq.)",
    host: "municode",
    municodeClientPath: "ventura_county",
    buildingCodeChapterUrl:
      "https://library.municode.com/ca/ventura_county/codes/code_of_ordinances?nodeId=VENCOCO_ORCO_DIVVIIIBURE",
    keyAmendmentSections: [
      "8101",     // Building Code adoption + admin amendments
      "8101.5",   // Green Building Standards
      "8102",     // Residential Code (CRC adoption)
      "8103",     // Electrical Code
      "8104",     // Plumbing Code
      "8105",     // Mechanical Code
      "8107",     // Fire Code (WUI/VHFHSZ adoption hooks)
      "8108",     // Energy Code
    ],
    aduSectionUrl:
      "https://library.municode.com/ca/ventura_county/codes/code_of_ordinances?nodeId=VENCOCO_ORCO_DIVVIIIBURE_CH82ZO",
    keyAmendmentTopics: [
      "VHFHSZ construction (CBC Chapter 7A) — large wildfire-exposed unincorporated areas",
      "Defensible space + Ch. 49 Fire Code requirements (Ventura County FPD)",
      "Agricultural building exemptions (CBC §312 + county overlays)",
      "Hillside grading ordinance (slope > 20% triggers geotech + drainage review)",
      "Ag-zoned ADU rules (county-specific, distinct from city ADU programs)",
      "Coastal Zone overlay (CA Coastal Commission — south county shoreline)",
    ],
    estimatedChunks: 35,
  },

  // ------------------------------------------------------------------
  // 4. SAN FRANCISCO — population ~875K
  // SF Building Code is on Municode as a separate volume.
  // SF has the most complex local code of any CA city (extensive amends).
  // ------------------------------------------------------------------
  {
    jurisdictionKey: "CA:SAN_FRANCISCO",
    cityName: "City and County of San Francisco",
    county: "San Francisco",
    ibcYear: "2022",
    adoptionOrdRef: "SF Admin Code Chapter 9",
    host: "municode",
    municodeClientPath: "san_francisco",
    buildingCodeChapterUrl:
      "https://library.municode.com/ca/san_francisco/codes/building_code",
    keyAmendmentSections: ["101.2", "101.3", "505.1", "703", "901", "1613A"],
    aduSectionUrl:
      "https://library.municode.com/ca/san_francisco/codes/planning_code?nodeId=SFPC_ART2ADUNST_207ADU",
    keyAmendmentTopics: [
      "Seismic retrofit (Chapter 16A — mandatory for wood-frame buildings)",
      "Soft-story retrofit program (SF Ordinance 72-13)",
      "ADU provisions (SF Planning Code Article 2, Section 207)",
      "Green Building Code (SFGBC — tiered above CALGreen)",
      "Accessible Business Entrance requirements (SF-specific)",
      "Historic preservation requirements (CEQA, Chapter 7 of SF Admin Code)",
    ],
    estimatedChunks: 55,
  },

  // ------------------------------------------------------------------
  // 5. SAN DIEGO CITY — population ~1.4M
  // SDMC Chapter 14 = Building Regulations
  // ------------------------------------------------------------------
  {
    jurisdictionKey: "CA:SAN_DIEGO",
    cityName: "City of San Diego",
    county: "San Diego",
    ibcYear: "2022",
    adoptionOrdRef: "SDMC §22.1101 et seq.",
    host: "municode",
    municodeClientPath: "san_diego",
    buildingCodeChapterUrl:
      "https://library.municode.com/ca/san_diego/codes/code_of_ordinances?nodeId=CH14BURE",
    keyAmendmentSections: ["14.01.001", "14.09.001", "14.11.001"],
    aduSectionUrl:
      "https://library.municode.com/ca/san_diego/codes/code_of_ordinances?nodeId=CH13ZOOREDEPR_AR3ADZORE_DIV3ORUSRE_SD131.0427ADUNUN",
    keyAmendmentTopics: [
      "Coastal zone amendments (SDMC Title 14 + Coastal Commission CDP)",
      "ADU ordinance (Title 13 zoning amendments, 2022)",
      "Stormwater amendments (Low Impact Development requirements)",
      "Fire code amendments (SDFD referral triggers)",
    ],
    estimatedChunks: 40,
  },

  // ------------------------------------------------------------------
  // 6. LONG BEACH — population ~460K
  // LBMC Chapter 18 = Building Code
  // ------------------------------------------------------------------
  {
    jurisdictionKey: "CA:LONG_BEACH",
    cityName: "City of Long Beach",
    county: "Los Angeles",
    ibcYear: "2022",
    adoptionOrdRef: "LBMC Chapter 18",
    host: "municode",
    municodeClientPath: "long_beach",
    buildingCodeChapterUrl:
      "https://library.municode.com/ca/long_beach/codes/code_of_ordinances?nodeId=LBMC_TIT18BUCO",
    keyAmendmentSections: [],
    keyAmendmentTopics: [
      "Port/industrial proximity amendments",
      "Coastal zone: LBMC + CA Coastal Commission CDP requirements",
      "ADU provisions (2022 updates)",
    ],
    estimatedChunks: 30,
  },

  // ------------------------------------------------------------------
  // 7. PASADENA — population ~140K
  // PMC Title 14 = Building Regulations
  // Heavy residential + ADU volume; hillside construction is common.
  // ------------------------------------------------------------------
  {
    jurisdictionKey: "CA:PASADENA",
    cityName: "City of Pasadena",
    county: "Los Angeles",
    ibcYear: "2022",
    adoptionOrdRef: "PMC §14.04.010 et seq.",
    host: "municode",
    municodeClientPath: "pasadena",
    buildingCodeChapterUrl:
      "https://library.municode.com/ca/pasadena/codes/code_of_ordinances?nodeId=PMC_TIT14BURE",
    keyAmendmentSections: ["14.04.010", "14.04.110"],
    keyAmendmentTopics: [
      "Hillside development standards (PMC Title 17)",
      "Historic preservation (Old Pasadena, Bungalow Heaven overlays)",
      "ADU regulations (PMC Title 17.50)",
      "Fire code amendments (Pasadena Fire Dept. referral requirements)",
    ],
    estimatedChunks: 35,
  },

  // ------------------------------------------------------------------
  // 8. GLENDALE — population ~195K
  // GMC Chapter 8.04 = Building Code
  // ------------------------------------------------------------------
  {
    jurisdictionKey: "CA:GLENDALE",
    cityName: "City of Glendale",
    county: "Los Angeles",
    ibcYear: "2022",
    adoptionOrdRef: "GMC §8.04.010 et seq.",
    host: "municode",
    municodeClientPath: "glendale_ca",
    buildingCodeChapterUrl:
      "https://library.municode.com/ca/glendale/codes/municipal_code?nodeId=GMC_CH8.04BUCO",
    keyAmendmentSections: [],
    keyAmendmentTopics: [
      "Hillside ordinance (grading, drainage, fire access roads)",
      "Residential sprinkler requirement (expanded beyond CBC triggers)",
      "ADU provisions",
    ],
    estimatedChunks: 30,
  },

  // ------------------------------------------------------------------
  // 9. BURBANK — population ~105K
  // BMC Chapter 10-1 = Building Code
  // ------------------------------------------------------------------
  {
    jurisdictionKey: "CA:BURBANK",
    cityName: "City of Burbank",
    county: "Los Angeles",
    ibcYear: "2022",
    adoptionOrdRef: "BMC §10-1-401 et seq.",
    host: "municode",
    municodeClientPath: "burbank",
    buildingCodeChapterUrl:
      "https://library.municode.com/ca/burbank/codes/municipal_code?nodeId=BMC_CH10-1BUCO",
    keyAmendmentSections: [],
    keyAmendmentTopics: [
      "Airport influence area (BUR Airport ALUCP requirements)",
      "Industrial/studio zoning adjacency requirements",
      "ADU provisions",
    ],
    estimatedChunks: 25,
  },

  // ------------------------------------------------------------------
  // 10. SANTA MONICA — population ~90K
  // SMMC Chapter 8.08 = Building Code
  // Extensive green building + coastal + ADU amendments.
  // ------------------------------------------------------------------
  {
    jurisdictionKey: "CA:SANTA_MONICA",
    cityName: "City of Santa Monica",
    county: "Los Angeles",
    ibcYear: "2022",
    adoptionOrdRef: "SMMC §8.08.010 et seq.",
    host: "municode",
    municodeClientPath: "santa_monica",
    buildingCodeChapterUrl:
      "https://library.municode.com/ca/santa_monica/codes/municipal_code?nodeId=SMMC_CH8.08BUCO",
    keyAmendmentSections: [],
    aduSectionUrl:
      "https://library.municode.com/ca/santa_monica/codes/municipal_code?nodeId=SMMC_CH9.28ADUN",
    keyAmendmentTopics: [
      "Coastal zone amendments (CCC CDP + SM LCP)",
      "Reach Code — all-electric building requirements (gas prohibition)",
      "ADU ordinance (Chapter 9.28 — among most permissive in CA)",
      "Green building program (Tier 1–3 above CALGreen)",
    ],
    estimatedChunks: 40,
  },

  // ------------------------------------------------------------------
  // 11. ANAHEIM — population ~350K
  // AMC Chapter 15.04 = Building Code
  // ------------------------------------------------------------------
  {
    jurisdictionKey: "CA:ANAHEIM",
    cityName: "City of Anaheim",
    county: "Orange",
    ibcYear: "2022",
    adoptionOrdRef: "AMC §15.04.010 et seq.",
    host: "municode",
    municodeClientPath: "anaheim",
    buildingCodeChapterUrl:
      "https://library.municode.com/ca/anaheim/codes/code_of_ordinances?nodeId=AMC_TIT15BUCO_CH15.04BUCO",
    keyAmendmentSections: [],
    keyAmendmentTopics: [
      "Resort/hospitality district amendments (Disneyland area height overlays)",
      "Orange County Fire Authority (OCFA) code compliance requirements",
      "ADU provisions",
    ],
    estimatedChunks: 25,
  },

  // ------------------------------------------------------------------
  // 12. IRVINE — population ~310K
  // IMC Chapter 3-3 = Building Code
  // ------------------------------------------------------------------
  {
    jurisdictionKey: "CA:IRVINE",
    cityName: "City of Irvine",
    county: "Orange",
    ibcYear: "2022",
    adoptionOrdRef: "IMC §3-3-1 et seq.",
    host: "municode",
    municodeClientPath: "irvine",
    buildingCodeChapterUrl:
      "https://library.municode.com/ca/irvine/codes/municipal_code?nodeId=IMC_PT3BURE_CH3-3BUCO",
    keyAmendmentSections: [],
    keyAmendmentTopics: [
      "Planned community (PC) zoning — Irvine Company master plan areas",
      "OCFA fire code compliance",
      "ADU provisions (Irvine has above-average ADU permitting)",
      "All-electric reach code (per 2022 adoption)",
    ],
    estimatedChunks: 25,
  },

  // ------------------------------------------------------------------
  // 13. OAKLAND — population ~430K
  // OMC Chapter 15.04 = Building Code
  // ------------------------------------------------------------------
  {
    jurisdictionKey: "CA:OAKLAND",
    cityName: "City of Oakland",
    county: "Alameda",
    ibcYear: "2022",
    adoptionOrdRef: "OMC §15.04.010 et seq.",
    host: "municode",
    municodeClientPath: "oakland",
    buildingCodeChapterUrl:
      "https://library.municode.com/ca/oakland/codes/code_of_ordinances?nodeId=OMC_TIT15BURE_CH15.04BUCO",
    keyAmendmentSections: [],
    keyAmendmentTopics: [
      "Seismic safety (soft-story and non-ductile concrete retrofit programs)",
      "WUI hillside overlay (Oakland Hills — Very High FHSZ)",
      "ADU provisions (Oakland was an early adopter of aggressive ADU rules)",
      "All-electric building requirements (Oakland 2022 reach code)",
    ],
    estimatedChunks: 35,
  },

  // ------------------------------------------------------------------
  // 14. SAN JOSE — population ~1M
  // SJMC Title 17 = Building Regulations
  // ------------------------------------------------------------------
  {
    jurisdictionKey: "CA:SAN_JOSE",
    cityName: "City of San Jose",
    county: "Santa Clara",
    ibcYear: "2022",
    adoptionOrdRef: "SJMC §17.04.010 et seq.",
    host: "municode",
    municodeClientPath: "san_jose",
    buildingCodeChapterUrl:
      "https://library.municode.com/ca/san_jose/codes/code_of_ordinances?nodeId=SJMC_TIT17BURE",
    keyAmendmentSections: [],
    aduSectionUrl:
      "https://library.municode.com/ca/san_jose/codes/code_of_ordinances?nodeId=SJMC_TIT20ZORE_PTIIZOZO_CH20.80ADADUN",
    keyAmendmentTopics: [
      "Reach code — all-electric new construction",
      "ADU ordinance (SJMC Title 20.80 — among most active ADU programs in Bay Area)",
      "Wildfire buffer zone requirements (eastern foothills — Very High FHSZ)",
      "Seismic updates (soft-story inventory program)",
    ],
    estimatedChunks: 35,
  },

  // ------------------------------------------------------------------
  // 15. SACRAMENTO — population ~530K
  // SCC Title 15 = Building Code
  // ------------------------------------------------------------------
  {
    jurisdictionKey: "CA:SACRAMENTO",
    cityName: "City of Sacramento",
    county: "Sacramento",
    ibcYear: "2022",
    adoptionOrdRef: "SCC §15.04.010 et seq.",
    host: "municode",
    municodeClientPath: "sacramento",
    buildingCodeChapterUrl:
      "https://library.municode.com/ca/sacramento/codes/code_of_ordinances?nodeId=SCC_TIT15BURE_CH15.04BUCO",
    keyAmendmentSections: [],
    keyAmendmentTopics: [
      "All-electric reach code (Sacramento 2022 Reach Code)",
      "Flood management amendments (Sacramento levee district)",
      "ADU provisions (Sacramento adopted AB 68 aggressively)",
      "Urban forestry requirements (tree canopy preservation during construction)",
    ],
    estimatedChunks: 30,
  },
];

// Total: ~530 chunks across 15 jurisdictions
export function amendmentTotalChunks(): number {
  return CA_AMENDMENT_SOURCES.reduce((s, src) => s + src.estimatedChunks, 0);
}

export function getAmendmentSource(jurisdictionKey: string): AmendmentSource | null {
  return CA_AMENDMENT_SOURCES.find(s => s.jurisdictionKey === jurisdictionKey) ?? null;
}
