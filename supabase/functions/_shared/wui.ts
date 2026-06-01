// =====================================================================
// CalFire FHSZ (Fire Hazard Severity Zone) GIS overlay.
//
// Given a project address, this module:
//   1. Geocodes it to lat/lng via the free US Census Geocoder
//      (no API key required, free, returns .gov-sourced coordinates)
//   2. Queries CalFire's public ArcGIS REST service to determine if
//      the parcel falls in a designated FHSZ zone
//   3. Returns a structured WuiZoneResult with the zone classification
//
// Why this matters:
//   Projects in "High" or "Very High" FHSZ zones must comply with
//   CBC Chapter 7A (wildfire-resistive construction materials and
//   methods). This is a mandatory code path that plan reviewers must
//   verify, but it requires address-level GIS data that plan text
//   alone cannot provide.
//
// CalFire FHSZ GIS service:
//   https://egis.fire.ca.gov/arcgis/rest/services/FHSZ/FHSZ/MapServer
//   Layer 0: State Responsibility Area (SRA) FHSZ
//   Layer 1: Local Responsibility Area (LRA) Very High FHSZ
//   (LRA Very High zones are locally designated and reviewed by CAL FIRE)
//
// US Census Geocoder (free, no key):
//   https://geocoding.geo.census.gov/geocoder/locations/onelineaddress
//
// Caching:
//   Results are stored in the wui_zone_cache Postgres table (added in
//   migration 0003) keyed on a normalized address hash.
//   TTL: 1 year (zone boundaries don't change often; re-query on expiry).
// =====================================================================

import { SupabaseClient } from "https://esm.sh/@supabase/supabase-js@2.45.0";

export type FhszClass = "Moderate" | "High" | "Very High";
export type SraType = "SRA" | "LRA" | "FRA";

export interface WuiZoneResult {
  in_wui: boolean;
  haz_class: FhszClass | null;
  sra_type: SraType | null;
  county: string | null;
  state: string | null;      // 'CA' when resolved from CalFire
  lat: number | null;
  lng: number | null;
  matched_address: string | null;
  source: "calfire_fhsz";
  // null means geocode failed or no CalFire layer intersected (project not in CA)
  error?: string;
}

// =====================================================================
// CalFire FHSZ ArcGIS REST endpoints
// =====================================================================
const CALFIRE_SRA_URL =
  "https://egis.fire.ca.gov/arcgis/rest/services/FHSZ/FHSZ/MapServer/0/query";
const CALFIRE_LRA_URL =
  "https://egis.fire.ca.gov/arcgis/rest/services/FHSZ/FHSZ/MapServer/1/query";

// US Census Geocoder — free, no API key needed
const CENSUS_GEOCODER_URL =
  "https://geocoding.geo.census.gov/geocoder/locations/onelineaddress";

const GEOCODE_TIMEOUT_MS = 10_000;
const GIS_TIMEOUT_MS = 10_000;

// =====================================================================
// Step 1: Geocode address → lat/lng
// =====================================================================
interface GeocodedAddress {
  lat: number;
  lng: number;
  matched_address: string;
}

async function geocodeAddress(address: string): Promise<GeocodedAddress | null> {
  const params = new URLSearchParams({
    address,
    benchmark: "Public_AR_Current",
    format: "json",
  });
  const url = `${CENSUS_GEOCODER_URL}?${params}`;

  const ac = new AbortController();
  const timer = setTimeout(() => ac.abort("geocode timeout"), GEOCODE_TIMEOUT_MS);
  try {
    const r = await fetch(url, { signal: ac.signal });
    if (!r.ok) return null;
    const j = await r.json();
    const matches: Array<{
      matchedAddress: string;
      coordinates: { x: number; y: number };
    }> = j?.result?.addressMatches ?? [];
    if (!matches.length) return null;
    const best = matches[0];
    return {
      lat: best.coordinates.y,
      lng: best.coordinates.x,
      matched_address: best.matchedAddress,
    };
  } catch {
    return null;
  } finally {
    clearTimeout(timer);
  }
}

// =====================================================================
// Step 2: Query CalFire FHSZ ArcGIS service for a point
// =====================================================================
interface FhszFeatureAttrs {
  HAZ_CLASS?: string;  // 'Moderate', 'High', 'Very High' (or numeric 1/2/3)
  SRA?: string;        // 'SRA', 'LRA', 'FRA'
  COUNTY?: string;
  HAZ_DES?: string;    // alternate field name on LRA layer
  JURISDICTI?: string; // LRA jurisdiction
}

function normalizeHazClass(raw: string | number | null | undefined): FhszClass | null {
  if (raw == null) return null;
  const s = String(raw).trim();
  if (/very\s*high|3/i.test(s)) return "Very High";
  if (/^high$|^2$/i.test(s)) return "High";
  if (/moderate|1/i.test(s)) return "Moderate";
  return null;
}

async function queryFhszLayer(
  layerUrl: string,
  lat: number,
  lng: number,
): Promise<FhszFeatureAttrs | null> {
  const params = new URLSearchParams({
    geometry: `${lng},${lat}`,
    geometryType: "esriGeometryPoint",
    inSR: "4326",
    spatialRel: "esriSpatialRelIntersects",
    outFields: "HAZ_CLASS,SRA,COUNTY,HAZ_DES,JURISDICTI",
    returnGeometry: "false",
    f: "json",
  });

  const ac = new AbortController();
  const timer = setTimeout(() => ac.abort("gis timeout"), GIS_TIMEOUT_MS);
  try {
    const r = await fetch(`${layerUrl}?${params}`, { signal: ac.signal });
    if (!r.ok) return null;
    const j = await r.json();
    const features = j?.features ?? [];
    if (!features.length) return null;
    return (features[0]?.attributes as FhszFeatureAttrs) ?? null;
  } catch {
    return null;
  } finally {
    clearTimeout(timer);
  }
}

// =====================================================================
// Step 3: Combine SRA + LRA results into a final WuiZoneResult
// =====================================================================
async function resolveZoneFromCoords(
  lat: number,
  lng: number,
  matchedAddress: string,
): Promise<WuiZoneResult> {
  // Query both layers concurrently — we want the most hazardous designation
  const [sra, lra] = await Promise.all([
    queryFhszLayer(CALFIRE_SRA_URL, lat, lng),
    queryFhszLayer(CALFIRE_LRA_URL, lat, lng),
  ]);

  // SRA takes precedence for zone classification (state-designated)
  const primary = sra ?? lra ?? null;
  if (!primary) {
    // No FHSZ layer intersected — point is not in a designated zone
    return {
      in_wui: false,
      haz_class: null,
      sra_type: null,
      county: null,
      state: "CA",
      lat,
      lng,
      matched_address: matchedAddress,
      source: "calfire_fhsz",
    };
  }

  // Prefer the more severe classification (LRA Very High can exist even without SRA)
  const sraClass = normalizeHazClass(sra?.HAZ_CLASS ?? sra?.HAZ_DES);
  const lraClass = normalizeHazClass(lra?.HAZ_CLASS ?? lra?.HAZ_DES);
  const SEV: Record<string, number> = { "Very High": 3, "High": 2, "Moderate": 1 };
  let finalClass: FhszClass | null;
  if (!sraClass && !lraClass) {
    finalClass = null;
  } else if (!sraClass) {
    finalClass = lraClass;
  } else if (!lraClass) {
    finalClass = sraClass;
  } else {
    finalClass = (SEV[sraClass] >= SEV[lraClass]) ? sraClass : lraClass;
  }

  const sraType: SraType | null =
    primary.SRA === "SRA" ? "SRA" :
    primary.SRA === "LRA" ? "LRA" :
    primary.SRA === "FRA" ? "FRA" :
    lra ? "LRA" : null;

  const in_wui = finalClass === "High" || finalClass === "Very High";

  return {
    in_wui,
    haz_class: finalClass,
    sra_type: sraType,
    county: primary.COUNTY ?? lra?.COUNTY ?? null,
    state: "CA",
    lat,
    lng,
    matched_address: matchedAddress,
    source: "calfire_fhsz",
  };
}

// =====================================================================
// Caching helpers
// =====================================================================

/** Normalize an address string into a stable cache key. */
function normalizeAddress(address: string): string {
  return address.toLowerCase().replace(/[^\w\s]/g, "").replace(/\s+/g, " ").trim();
}

/** Simple non-crypto hash — good enough for a cache key without pgcrypto overhead. */
function simpleHash(s: string): string {
  let h = 5381;
  for (let i = 0; i < s.length; i++) h = ((h << 5) + h) ^ s.charCodeAt(i);
  return (h >>> 0).toString(16).padStart(8, "0");
}

async function lookupCached(
  supabase: SupabaseClient,
  addressHash: string,
): Promise<WuiZoneResult | null> {
  const { data } = await supabase
    .from("wui_zone_cache")
    .select("*")
    .eq("address_hash", addressHash)
    .gt("expires_at", new Date().toISOString())
    .limit(1)
    .maybeSingle();
  if (!data) return null;
  return {
    in_wui: data.in_wui,
    haz_class: data.haz_class as FhszClass | null,
    sra_type: data.sra_type as SraType | null,
    county: data.county,
    state: data.state,
    lat: data.lat,
    lng: data.lng,
    matched_address: data.matched_address,
    source: "calfire_fhsz",
  };
}

async function storeInCache(
  supabase: SupabaseClient,
  addressInput: string,
  addressHash: string,
  result: WuiZoneResult,
): Promise<void> {
  await supabase.from("wui_zone_cache").upsert({
    address_input: addressInput,
    address_hash: addressHash,
    matched_address: result.matched_address,
    lat: result.lat,
    lng: result.lng,
    haz_class: result.haz_class,
    sra_type: result.sra_type,
    county: result.county,
    in_wui: result.in_wui,
    state: result.state,
    cached_at: new Date().toISOString(),
    expires_at: new Date(Date.now() + 365 * 24 * 60 * 60 * 1000).toISOString(),
  }, { onConflict: "address_hash" });
}

// =====================================================================
// Public API
// =====================================================================

/**
 * Resolve the CalFire FHSZ WUI zone for a project address.
 *
 * Returns null if:
 *  - The address is not in California (CalFire only covers CA)
 *  - Geocoding fails (invalid address, service unavailable)
 *  - We cannot determine whether it's CA from the address string
 *
 * Pass a supabase client to enable result caching (recommended).
 *
 * @param address   Full project address, e.g. "123 Main St, Los Angeles, CA 90012"
 * @param supabase  Optional — enables caching; skip in unit test contexts.
 */
export async function getWuiZone(
  address: string,
  supabase?: SupabaseClient,
): Promise<WuiZoneResult | null> {
  if (!address?.trim()) return null;

  // Only applicable for CA addresses
  if (!/\bCA\b|california/i.test(address)) return null;

  const normalized = normalizeAddress(address);
  const addressHash = simpleHash(normalized);

  // Cache lookup
  if (supabase) {
    const cached = await lookupCached(supabase, addressHash);
    if (cached) return cached;
  }

  // Geocode
  const geo = await geocodeAddress(address);
  if (!geo) {
    // Geocoding failed; return null rather than erroring the whole pipeline
    console.warn(`[wui] geocode failed for: ${address}`);
    return null;
  }

  // GIS lookup
  const result = await resolveZoneFromCoords(geo.lat, geo.lng, geo.matched_address);

  // Store in cache (fire-and-forget; don't block the pipeline on cache write errors)
  if (supabase) {
    storeInCache(supabase, address, addressHash, result).catch(e =>
      console.warn("[wui] cache store failed:", e),
    );
  }

  return result;
}

// =====================================================================
// Utility: human-readable zone description for rule summaries
// =====================================================================
export function describeWuiZone(wui: WuiZoneResult): string {
  if (!wui.in_wui && !wui.haz_class) {
    return `Not in a designated CalFire FHSZ zone (${wui.county ?? "county unknown"}).`;
  }
  const county = wui.county ? ` in ${wui.county} County` : "";
  const sra = wui.sra_type ? ` (${wui.sra_type})` : "";
  return `${wui.haz_class ?? "Unknown"} Fire Hazard Severity Zone${sra}${county}. CBC Chapter 7A wildfire-resistive construction requirements apply.`;
}
