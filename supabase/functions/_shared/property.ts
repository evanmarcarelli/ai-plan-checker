// =====================================================================
// Property profile resolver — Session C
//
// Given a project address, resolves all address-specific regulatory
// overlays in a single async pass:
//
//   1. Geocode (US Census — free, no key)       ← already in wui.ts
//   2. CalFire FHSZ WUI zone (CA only)          ← wui.ts
//   3. FEMA NFHL flood zone (nationwide, free)
//   4. CA Coastal Commission zone (CA only)
//   5. LA County parcel / zoning (LA addresses)
//   6. LADBS permit history (LA City only)
//
// Each lookup is independent and fails gracefully — a GIS timeout
// does not abort the rest of the property resolution.
//
// All results are cached in property_lookup_cache (migration 0005).
// WUI zone uses its own wui_zone_cache (migration 0003).
//
// The PropertyProfile is passed to the Surveyor which incorporates it
// into the JurisdictionProfile. The triage runner then attaches it to
// the submittal scope for rule evaluation and researcher context.
// =====================================================================

import { SupabaseClient } from "https://esm.sh/@supabase/supabase-js@2.45.0";
import { WuiZoneResult, getWuiZone } from "./wui.ts";

const GIS_TIMEOUT_MS = 12_000;

// =====================================================================
// FEMA National Flood Hazard Layer (NFHL)
// Free public ArcGIS REST service — no API key.
//
// Zone codes: https://www.fema.gov/flood-maps/national-flood-hazard-layer
//   A, AE, AH, AO, AR, A99   → High risk (1% annual chance, SFHA)
//   V, VE                    → Coastal high risk (SFHA + wave action)
//   X                        → Moderate/Low risk (outside SFHA)
//   D                        → Undetermined
// =====================================================================
const FEMA_NFHL_URL =
  "https://msc.fema.gov/arcgis/rest/services/NFHL_floodHazard/NFHL/MapServer/28/query";

export type FloodZoneCode = "AE" | "AH" | "AO" | "AR" | "A" | "A99" | "V" | "VE" | "X" | "D" | string;

export interface FloodZoneResult {
  in_sfha: boolean;         // Special Flood Hazard Area (high risk)
  zone_code: FloodZoneCode; // e.g. 'AE', 'X', 'VE'
  zone_subtype: string | null;
  base_flood_elevation_ft: number | null;
  panel_id: string | null;
  source: "fema_nfhl";
}

async function lookupFloodZone(
  lat: number, lng: number,
): Promise<FloodZoneResult | null> {
  const params = new URLSearchParams({
    geometry: `${lng},${lat}`,
    geometryType: "esriGeometryPoint",
    inSR: "4326",
    spatialRel: "esriSpatialRelIntersects",
    outFields: "FLD_ZONE,ZONE_SUBTY,SFHA_TF,STATIC_BFE,PANEL_ID",
    returnGeometry: "false",
    f: "json",
  });

  try {
    const r = await fetch(`${FEMA_NFHL_URL}?${params}`, {
      signal: AbortSignal.timeout(GIS_TIMEOUT_MS),
    });
    if (!r.ok) return null;
    const j = await r.json();
    const attrs = j?.features?.[0]?.attributes;
    if (!attrs) return null;

    const zone: FloodZoneCode = attrs.FLD_ZONE ?? "D";
    const inSfha = attrs.SFHA_TF === "T"
      || /^A|^V/.test(zone);

    return {
      in_sfha: inSfha,
      zone_code: zone,
      zone_subtype: attrs.ZONE_SUBTY ?? null,
      base_flood_elevation_ft: attrs.STATIC_BFE != null
        ? Number(attrs.STATIC_BFE) : null,
      panel_id: attrs.PANEL_ID ?? null,
      source: "fema_nfhl",
    };
  } catch {
    return null;
  }
}

// =====================================================================
// California Coastal Commission — Coastal Zone boundary
//
// A project inside the Coastal Zone requires a Coastal Development
// Permit (CDP) from the Coastal Commission OR local coastal plan (LCP)
// compliance. This fundamentally changes the permitting pathway.
//
// Service: California Open Data ArcGIS feature service
// The coastal zone boundary is a polygon dataset; we do a point-in-poly.
// =====================================================================
const CA_COASTAL_ZONE_URL =
  "https://services.arcgis.com/sNNMPm0vu4u2MuD6/arcgis/rest/services/California_Coastal_Zone/FeatureServer/0/query";

export interface CoastalZoneResult {
  in_coastal_zone: boolean;
  // If true, the project needs a CDP from CCC or LCP compliance
  cdp_required: boolean;
  // Which segment name / region (Coastal Commission region)
  segment: string | null;
  source: "ca_coastal_commission";
}

async function lookupCoastalZone(
  lat: number, lng: number,
): Promise<CoastalZoneResult | null> {
  const params = new URLSearchParams({
    geometry: `${lng},${lat}`,
    geometryType: "esriGeometryPoint",
    inSR: "4326",
    spatialRel: "esriSpatialRelIntersects",
    outFields: "DISTRICT,REGION",
    returnGeometry: "false",
    f: "json",
  });

  try {
    const r = await fetch(`${CA_COASTAL_ZONE_URL}?${params}`, {
      signal: AbortSignal.timeout(GIS_TIMEOUT_MS),
    });
    if (!r.ok) return null;
    const j = await r.json();
    const features = j?.features ?? [];

    if (!features.length) {
      return {
        in_coastal_zone: false,
        cdp_required: false,
        segment: null,
        source: "ca_coastal_commission",
      };
    }

    const attrs = features[0].attributes ?? {};
    return {
      in_coastal_zone: true,
      cdp_required: true,
      segment: attrs.DISTRICT ?? attrs.REGION ?? null,
      source: "ca_coastal_commission",
    };
  } catch {
    return null;
  }
}

// =====================================================================
// LA County Parcel / Zoning lookup
//
// LA County's EGIS ArcGIS service provides parcel boundaries and
// zoning codes for all unincorporated LA County parcels. LA City
// parcels can also be queried via LADBS portal (see below).
//
// Service: LA County Enterprise GIS parcel layer
// =====================================================================
const LA_COUNTY_PARCEL_URL =
  "https://egis.lacounty.gov/arcgis/rest/services/CountyParcel/MapServer/0/query";
const LA_COUNTY_ZONING_URL =
  "https://egis.lacounty.gov/arcgis/rest/services/Zoning/MapServer/0/query";

export interface ParcelResult {
  apn: string | null;           // Assessor's Parcel Number
  zoning_code: string | null;   // e.g. 'R-1', 'C-2', 'M1'
  land_use_code: string | null;
  lot_area_sqft: number | null;
  jurisdiction: string | null;  // 'LA City', 'Unincorporated', 'Pasadena', etc.
  source: "la_county_gis";
}

async function lookupLACountyParcel(
  lat: number, lng: number,
): Promise<ParcelResult | null> {
  // Parcel APN lookup
  const params = new URLSearchParams({
    geometry: `${lng},${lat}`,
    geometryType: "esriGeometryPoint",
    inSR: "4326",
    spatialRel: "esriSpatialRelIntersects",
    outFields: "APN,ZONING,USE_CODE,SHAPE_AREA,JURIS",
    returnGeometry: "false",
    f: "json",
  });

  try {
    const r = await fetch(`${LA_COUNTY_PARCEL_URL}?${params}`, {
      signal: AbortSignal.timeout(GIS_TIMEOUT_MS),
    });
    if (!r.ok) return null;
    const j = await r.json();
    const attrs = j?.features?.[0]?.attributes;
    if (!attrs) return null;

    // Convert SHAPE_AREA from sq meters (ESRI default) to sq ft if needed
    const areaRaw = attrs.SHAPE_AREA ? Number(attrs.SHAPE_AREA) : null;
    // Heuristic: if area > 50,000 it's sq meters; convert to sq ft
    const areaSqft = areaRaw
      ? (areaRaw > 50_000 ? areaRaw * 10.7639 : areaRaw)
      : null;

    return {
      apn:            attrs.APN ?? null,
      zoning_code:    attrs.ZONING ?? null,
      land_use_code:  attrs.USE_CODE ?? null,
      lot_area_sqft:  areaSqft ? Math.round(areaSqft) : null,
      jurisdiction:   attrs.JURIS ?? null,
      source: "la_county_gis",
    };
  } catch {
    return null;
  }
}

// =====================================================================
// LADBS permit history (LA City only)
//
// Uses LA City Open Data portal (Socrata API, no key required for
// limited queries). Returns the 5 most recent permits on the parcel
// so the reviewer knows if there are open permits, prior corrections,
// or recent ADU activity.
// =====================================================================
const LADBS_PERMITS_URL =
  "https://data.lacity.org/resource/yv23-pmwf.json";

export interface LadBsPermit {
  permit_number: string;
  permit_type: string;
  work_description: string;
  permit_status: string;
  issue_date: string;
  address: string;
}

export interface LadBsResult {
  recentPermits: LadBsPermit[];
  openPermits: number;
  priorAduPermit: boolean;
  source: "ladbs_open_data";
}

async function lookupLADBSPermits(
  address: string,
): Promise<LadBsResult | null> {
  // Normalize address for Socrata query
  const normalized = address
    .toUpperCase()
    .replace(/,.*$/, "")      // strip city/state
    .replace(/\s+/g, " ")
    .trim();

  const params = new URLSearchParams({
    "$where": `address LIKE '${normalized.replace(/'/g, "''")}%'`,
    "$order": "issue_date DESC",
    "$limit": "10",
    "$select": "permit_nbr,permit_type,work_description,permit_status,issue_date,address",
  });

  try {
    const r = await fetch(`${LADBS_PERMITS_URL}?${params}`, {
      signal: AbortSignal.timeout(10_000),
      headers: { "Accept": "application/json" },
    });
    if (!r.ok) return null;
    const permits = await r.json();
    if (!Array.isArray(permits)) return null;

    const mapped: LadBsPermit[] = permits.map((p: Record<string, string>) => ({
      permit_number:    p.permit_nbr ?? "",
      permit_type:      p.permit_type ?? "",
      work_description: p.work_description ?? "",
      permit_status:    p.permit_status ?? "",
      issue_date:       p.issue_date ?? "",
      address:          p.address ?? "",
    }));

    const openPermits = mapped.filter(p =>
      /open|active|pending|issued/i.test(p.permit_status),
    ).length;

    const priorAduPermit = mapped.some(p =>
      /\badu\b|accessory\s+dwelling|junior\s+adu|jadu/i.test(p.work_description),
    );

    return {
      recentPermits: mapped.slice(0, 5),
      openPermits,
      priorAduPermit,
      source: "ladbs_open_data",
    };
  } catch {
    return null;
  }
}

// =====================================================================
// PropertyProfile — the unified output
// =====================================================================
export interface PropertyProfile {
  address: string;
  matched_address: string | null;
  lat: number | null;
  lng: number | null;
  // Overlays
  wui_zone: WuiZoneResult | null;
  flood_zone: FloodZoneResult | null;
  coastal_zone: CoastalZoneResult | null;
  parcel: ParcelResult | null;
  ladbs: LadBsResult | null;
  // Resolution metadata
  resolved_at: string;
  resolution_errors: string[];  // non-fatal errors for diagnostics
}

// =====================================================================
// Caching helpers (property_lookup_cache from migration 0005)
// =====================================================================
function addressHash(address: string): string {
  const norm = address.toLowerCase().replace(/[^\w\s]/g, "").replace(/\s+/g, " ").trim();
  let h = 5381;
  for (let i = 0; i < norm.length; i++) h = ((h << 5) + h) ^ norm.charCodeAt(i);
  return (h >>> 0).toString(16).padStart(8, "0");
}

async function getCachedProfile(
  supabase: SupabaseClient,
  hash: string,
): Promise<PropertyProfile | null> {
  const { data } = await supabase
    .from("property_lookup_cache")
    .select("profile_json")
    .eq("address_hash", hash)
    .gt("expires_at", new Date().toISOString())
    .maybeSingle();
  return data ? (data.profile_json as PropertyProfile) : null;
}

async function cacheProfile(
  supabase: SupabaseClient,
  hash: string,
  address: string,
  profile: PropertyProfile,
): Promise<void> {
  await supabase.from("property_lookup_cache").upsert({
    address_hash: hash,
    address_input: address,
    profile_json: profile,
    resolved_at: profile.resolved_at,
    expires_at: new Date(Date.now() + 30 * 24 * 60 * 60 * 1000).toISOString(), // 30 days
  }, { onConflict: "address_hash" }).catch(e =>
    console.warn("[property] cache write failed:", e)
  );
}

// =====================================================================
// Public API: resolvePropertyProfile
//
// Geocodes the address once then fans out to all applicable GIS APIs
// concurrently. Returns a PropertyProfile with all available overlays.
//
// Non-fatal: any single lookup failure leaves that field null and
// appends to resolution_errors — it never aborts the whole profile.
//
// @param address     Full project address with city + state
// @param supabase    Service-role client (for caching)
// @param options.skipLadbs   Skip LADBS lookup (not LA City)
// @param options.skipCoastal Skip Coastal lookup (not CA)
// =====================================================================
export async function resolvePropertyProfile(
  address: string,
  supabase?: SupabaseClient,
  options: {
    skipLadbs?: boolean;
    skipCoastal?: boolean;
    skipParcel?: boolean;
  } = {},
): Promise<PropertyProfile> {
  const errors: string[] = [];
  const hash = addressHash(address);

  // Cache lookup
  if (supabase) {
    const cached = await getCachedProfile(supabase, hash);
    if (cached) return cached;
  }

  // ---- 1. Geocode (via wui.ts — reuse the Census geocoder) ----------
  // Import getWuiZone which already geocodes and returns lat/lng
  const wuiResult = await getWuiZone(address, supabase).catch(e => {
    errors.push(`WUI: ${(e as Error).message}`);
    return null;
  });

  const lat = wuiResult?.lat ?? null;
  const lng = wuiResult?.lng ?? null;
  const matchedAddress = wuiResult?.matched_address ?? null;

  // If geocode failed entirely, return a minimal profile
  if (!lat || !lng) {
    const profile: PropertyProfile = {
      address, matched_address: null, lat: null, lng: null,
      wui_zone: null, flood_zone: null, coastal_zone: null,
      parcel: null, ladbs: null,
      resolved_at: new Date().toISOString(),
      resolution_errors: ["geocode failed; all GIS lookups skipped"],
    };
    if (supabase) await cacheProfile(supabase, hash, address, profile);
    return profile;
  }

  // ---- 2. Fan-out all GIS lookups concurrently ----------------------
  const isCalifornia = /\bCA\b|california/i.test(address);
  const isLACity = /los angeles/i.test(address) && isCalifornia;
  const isLACounty = isCalifornia && /los angeles|pasadena|glendale|burbank|santa monica|long beach/i.test(address);

  const [flood, coastal, parcel, ladbs] = await Promise.all([
    // FEMA flood zone — runs for all US addresses
    lookupFloodZone(lat, lng).catch(e => {
      errors.push(`FEMA flood: ${(e as Error).message}`);
      return null;
    }),

    // CA Coastal zone — CA only
    (isCalifornia && !options.skipCoastal)
      ? lookupCoastalZone(lat, lng).catch(e => {
          errors.push(`Coastal: ${(e as Error).message}`);
          return null;
        })
      : Promise.resolve(null),

    // LA County parcel / zoning — LA County addresses only
    (isLACounty && !options.skipParcel)
      ? lookupLACountyParcel(lat, lng).catch(e => {
          errors.push(`LA Parcel: ${(e as Error).message}`);
          return null;
        })
      : Promise.resolve(null),

    // LADBS permit history — LA City only
    (isLACity && !options.skipLadbs)
      ? lookupLADBSPermits(address).catch(e => {
          errors.push(`LADBS: ${(e as Error).message}`);
          return null;
        })
      : Promise.resolve(null),
  ]);

  const profile: PropertyProfile = {
    address,
    matched_address: matchedAddress,
    lat,
    lng,
    wui_zone:    wuiResult,
    flood_zone:  flood,
    coastal_zone: coastal,
    parcel,
    ladbs,
    resolved_at: new Date().toISOString(),
    resolution_errors: errors,
  };

  if (supabase) await cacheProfile(supabase, hash, address, profile);

  return profile;
}

// =====================================================================
// Render property profile as a context block for the researcher
// =====================================================================
export function renderPropertyProfileForResearcher(profile: PropertyProfile): string {
  const lines: string[] = ["Property overlay data for this project address:"];

  // Flood zone
  if (profile.flood_zone) {
    const f = profile.flood_zone;
    if (f.in_sfha) {
      lines.push(`FLOOD ZONE: ${f.zone_code}${f.zone_subtype ? ` (${f.zone_subtype})` : ""} — HIGH RISK (Special Flood Hazard Area). IBC/CBC flood provisions apply. FEMA Elevation Certificate likely required.`);
    } else {
      lines.push(`FLOOD ZONE: Zone ${f.zone_code} — minimal flood risk. Standard drainage provisions apply.`);
    }
  }

  // Coastal zone
  if (profile.coastal_zone?.in_coastal_zone) {
    lines.push(`COASTAL ZONE: Project is inside the California Coastal Zone${profile.coastal_zone.segment ? ` (${profile.coastal_zone.segment})` : ""}. A Coastal Development Permit (CDP) is required from the Coastal Commission or under the local LCP. Verify CDP status before substantive review.`);
  }

  // Parcel / zoning
  if (profile.parcel) {
    const p = profile.parcel;
    const parts = [
      p.apn && `APN: ${p.apn}`,
      p.zoning_code && `Zoning: ${p.zoning_code}`,
      p.land_use_code && `Land use: ${p.land_use_code}`,
      p.lot_area_sqft && `Lot: ${p.lot_area_sqft.toLocaleString()} sf`,
      p.jurisdiction && `Jurisdiction: ${p.jurisdiction}`,
    ].filter(Boolean);
    if (parts.length) lines.push(`PARCEL: ${parts.join(" | ")}`);
  }

  // LADBS
  if (profile.ladbs) {
    const l = profile.ladbs;
    if (l.openPermits > 0) {
      lines.push(`LADBS: ${l.openPermits} open permit(s) on file. Reviewer should check for conflicts with active work.`);
    }
    if (l.priorAduPermit) {
      lines.push(`LADBS: Prior ADU permit(s) on record at this address.`);
    }
  }

  if (lines.length === 1) lines.push("No significant overlay designations found at this address.");

  return lines.join("\n");
}

// =====================================================================
// Injects property overlay rules into the scope's ambiguity list
// so they surface in reviewer questions.
// =====================================================================
export function propertyOverlayAmbiguities(profile: PropertyProfile): string[] {
  const items: string[] = [];

  if (profile.flood_zone?.in_sfha) {
    items.push(`Address is in FEMA Zone ${profile.flood_zone.zone_code} (SFHA). Confirm lowest-floor elevation and flood-proofing documentation are included.`);
  }
  if (profile.coastal_zone?.in_coastal_zone) {
    items.push("Address is in the California Coastal Zone. Confirm Coastal Development Permit (CDP) number is cited on the cover sheet.");
  }
  if (profile.wui_zone?.in_wui) {
    items.push(`Address is in a ${profile.wui_zone.haz_class} FHSZ. Verify CBC Chapter 7A wildfire-resistive material schedules are on the architectural drawings.`);
  }
  if (profile.ladbs?.openPermits) {
    items.push(`LADBS shows ${profile.ladbs.openPermits} open permit(s) at this address. Confirm this submittal doesn't conflict with active work.`);
  }

  return items;
}
