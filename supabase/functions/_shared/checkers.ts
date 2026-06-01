// =====================================================================
// Deterministic checker primitives.
//
// Pure functions over typed inputs. Everything here is unit-testable
// without touching Supabase, the LLM, or the web. The rule evaluator
// in evaluate.ts delegates the actual code-math to these functions so
// the LLM is never asked to do arithmetic — LLMs silently miscalculate
// 5–15% of the time on multi-step numeric reasoning, which is the
// fastest way to lose reviewer trust.
//
// Conventions:
//   - Inputs are the minimum required scalars (not the whole BuildingScope)
//     so each function is independently testable.
//   - Return shape is the same `CheckResult` for every checker so the
//     evaluator can wrap them uniformly.
//   - "info" is used when we can't evaluate (missing input). "warn" is
//     used when the result is technically a violation but the input is
//     ambiguous. "fail" requires a concrete, certain violation.
// =====================================================================
import { IBC_T506_2, IBC_T504_4, MIN_EXITS_BY_LOAD, HIGH_RISE_FT } from "./rules.ts";

export type CheckStatus = "pass" | "fail" | "warn" | "info";

export interface CheckResult {
  status: CheckStatus;
  summary: string;
  evidence?: string[];
}

const info = (summary: string): CheckResult => ({ status: "info", summary });
const pass = (summary: string, evidence?: string[]): CheckResult => ({ status: "pass", summary, evidence });
const fail = (summary: string, evidence?: string[]): CheckResult => ({ status: "fail", summary, evidence });
const warn = (summary: string, evidence?: string[]): CheckResult => ({ status: "warn", summary, evidence });

// =====================================================================
// Allowable area (IBC Table 506.2)
// =====================================================================
export interface AreaCheckInput {
  occupancyPrimary: string | null;
  constructionType: string | null;
  areaSf: number | null;
}

export function checkAllowableArea(input: AreaCheckInput): CheckResult {
  const { occupancyPrimary, constructionType, areaSf } = input;
  if (!occupancyPrimary || !constructionType) {
    return info("Cannot evaluate — occupancy or construction type missing.");
  }
  if (areaSf == null) return warn("Building area not declared.");
  const row = IBC_T506_2[occupancyPrimary];
  if (!row) return info(`No Table 506.2 row for ${occupancyPrimary}.`);
  const allowable = row[constructionType];
  if (allowable === undefined) return info(`Type ${constructionType} not in row for ${occupancyPrimary}.`);
  if (allowable === "UL") return pass("Unlimited area for this occupancy / type.");
  if (allowable === "NP") return fail(`${occupancyPrimary} NOT PERMITTED in Type ${constructionType}.`);
  if (areaSf > allowable) {
    return fail(
      `Area ${areaSf.toLocaleString()} sf exceeds tabular ${allowable.toLocaleString()} sf for ` +
      `Group ${occupancyPrimary} / Type ${constructionType}. Verify frontage and sprinkler increases under IBC 506.3.`,
      [`${areaSf.toLocaleString()} sf actual`, `${allowable.toLocaleString()} sf tabular`],
    );
  }
  return pass(`Area ${areaSf.toLocaleString()} sf within ${allowable.toLocaleString()} sf tabular limit.`);
}

// =====================================================================
// Allowable stories (IBC Table 504.4)
// =====================================================================
export interface StoriesCheckInput {
  occupancyPrimary: string | null;
  constructionType: string | null;
  storiesAbove: number | null;
  sprinklered: boolean | null;
}

export function checkAllowableStories(input: StoriesCheckInput): CheckResult {
  const { occupancyPrimary, constructionType, storiesAbove, sprinklered } = input;
  if (!occupancyPrimary || !constructionType) {
    return info("Cannot evaluate — occupancy or construction type missing.");
  }
  if (storiesAbove == null) return warn("Number of stories not declared.");
  const row = IBC_T504_4[occupancyPrimary];
  if (!row) return info(`No Table 504.4 row for ${occupancyPrimary}.`);
  const lim = row[constructionType];
  if (lim === "UL") return pass("Unlimited stories for this occupancy / type.");
  if (lim === "NP") return fail("Occupancy NOT PERMITTED in this construction type.");
  // Non-sprinklered: -1 floor from tabular (Table 504.4 footnote — simplified)
  const eff = sprinklered === false ? Math.max(1, (lim as number) - 1) : (lim as number);
  if (storiesAbove > eff) {
    return fail(
      `${storiesAbove} stories exceeds ${eff}-story limit (Table 504.4` +
      `${sprinklered === false ? ", non-sprinklered" : ""}).`,
    );
  }
  return pass(`${storiesAbove} stories within ${eff}-story limit.`);
}

// =====================================================================
// Minimum exits required (IBC 1006.3.2)
// =====================================================================
export function requiredMinExits(occupantLoad: number): number {
  return MIN_EXITS_BY_LOAD.find(b => occupantLoad <= b.maxLoad)!.exits;
}

export interface MinExitsInput {
  occupantLoad: number | null;
  declaredExits: number;
}

export function checkMinExits(input: MinExitsInput): CheckResult {
  if (input.occupantLoad == null) return info("Occupant load not declared.");
  const required = requiredMinExits(input.occupantLoad);
  if (input.declaredExits >= required) {
    return pass(`${input.declaredExits} exit(s); ${required} required for OL ${input.occupantLoad}.`);
  }
  return fail(`OL ${input.occupantLoad} requires ${required} exits; only ${input.declaredExits} labeled.`);
}

// =====================================================================
// Exit capacity (IBC 1005.3) — door 0.2 in/occ, stair 0.3 in/occ
// =====================================================================
export interface ExitCapacityInput {
  occupantLoad: number | null;
  declaredDoorWidthIn: number;   // sum of all door widths
  declaredStairWidthIn: number;  // sum of all stair widths
}

export function requiredDoorWidthIn(occupantLoad: number): number {
  return occupantLoad * 0.2;
}
export function requiredStairWidthIn(occupantLoad: number): number {
  return occupantLoad * 0.3;
}

export function checkExitCapacity(input: ExitCapacityInput): CheckResult {
  if (input.occupantLoad == null) return info("Occupant load not declared.");
  const reqDoor = requiredDoorWidthIn(input.occupantLoad);
  const reqStair = requiredStairWidthIn(input.occupantLoad);
  if (input.declaredDoorWidthIn === 0 && input.declaredStairWidthIn === 0) {
    return warn(`Need ≥${reqDoor.toFixed(1)}" total door width for OL ${input.occupantLoad}; no labeled exit doors found.`);
  }
  const issues: string[] = [];
  if (input.declaredDoorWidthIn && input.declaredDoorWidthIn < reqDoor) {
    issues.push(`door capacity ${input.declaredDoorWidthIn}" < ${reqDoor.toFixed(1)}" required`);
  }
  if (input.declaredStairWidthIn && input.declaredStairWidthIn < reqStair) {
    issues.push(`stair capacity ${input.declaredStairWidthIn}" < ${reqStair.toFixed(1)}" required`);
  }
  if (issues.length) {
    return fail(`Exit capacity insufficient for OL ${input.occupantLoad}: ${issues.join("; ")}.`);
  }
  return pass(`Exit capacity OK for OL ${input.occupantLoad}.`);
}

// =====================================================================
// High-rise threshold (IBC 403)
// =====================================================================
export function isHighRise(heightFt: number | null): boolean {
  return heightFt != null && heightFt > HIGH_RISE_FT;
}

// =====================================================================
// Plumbing fixtures (IPC Table 403.1) — abbreviated ratios
// =====================================================================
const FIXTURE_RATIOS: Record<string, { wc: number; lav: number }> = {
  "A":   { wc: 75,  lav: 200 },
  "B":   { wc: 25,  lav: 40  },
  "E":   { wc: 50,  lav: 50  },
  "F":   { wc: 100, lav: 100 },
  "I":   { wc: 25,  lav: 25  },
  "M":   { wc: 500, lav: 750 },
  "R-1": { wc: 10,  lav: 10  },
  "R-2": { wc: 10,  lav: 10  },
  "S":   { wc: 100, lav: 100 },
};

export interface FixtureCheckInput {
  occupancyPrimary: string | null;
  occupantLoad: number | null;
  actualWc: number | null;
  actualLav: number | null;
}

export function requiredFixtureCount(
  occupancyPrimary: string,
  occupantLoad: number,
): { wc: number; lav: number } | null {
  const key = FIXTURE_RATIOS[occupancyPrimary] ? occupancyPrimary : occupancyPrimary.charAt(0);
  const r = FIXTURE_RATIOS[key];
  if (!r) return null;
  return { wc: Math.ceil(occupantLoad / r.wc), lav: Math.ceil(occupantLoad / r.lav) };
}

export function checkFixtures(input: FixtureCheckInput): CheckResult {
  if (input.occupantLoad == null || !input.occupancyPrimary) {
    return info("Cannot calculate fixtures without occupant load + occupancy.");
  }
  const req = requiredFixtureCount(input.occupancyPrimary, input.occupantLoad);
  if (!req) return info(`No fixture ratios for ${input.occupancyPrimary}.`);
  if (input.actualWc == null && input.actualLav == null) {
    return warn(`Need ≥${req.wc} WC / ${req.lav} lav for OL ${input.occupantLoad}; no fixture schedule found.`);
  }
  const issues: string[] = [];
  if (input.actualWc != null && input.actualWc < req.wc) issues.push(`WC ${input.actualWc} < ${req.wc} required`);
  if (input.actualLav != null && input.actualLav < req.lav) issues.push(`Lav ${input.actualLav} < ${req.lav} required`);
  if (issues.length) return fail(`Fixtures short: ${issues.join("; ")}.`);
  return pass(`Fixtures OK: ${input.actualWc ?? "?"} WC / ${input.actualLav ?? "?"} lav meet ${req.wc} / ${req.lav}.`);
}
