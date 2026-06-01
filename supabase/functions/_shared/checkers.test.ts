// =====================================================================
// Unit tests for checkers.ts.
//
// Run: deno test --allow-none supabase/functions/_shared/checkers.test.ts
//
// Every numeric / table-driven check goes here. If a checker silently
// drifts when prompts or models change, this catches it before the
// eval set does.
// =====================================================================
import { assertEquals } from "https://deno.land/std@0.224.0/assert/mod.ts";
import {
  checkAllowableArea, checkAllowableStories, checkMinExits, checkExitCapacity,
  checkFixtures, requiredMinExits, requiredDoorWidthIn, requiredStairWidthIn,
  requiredFixtureCount, isHighRise,
} from "./checkers.ts";

// ---------------------------------------------------------------------
// checkAllowableArea  (IBC Table 506.2)
// ---------------------------------------------------------------------
Deno.test("allowable area — B/V-B at exactly tabular limit passes", () => {
  const r = checkAllowableArea({ occupancyPrimary: "B", constructionType: "V-B", areaSf: 9000 });
  assertEquals(r.status, "pass");
});

Deno.test("allowable area — B/V-B one sf over tabular fails", () => {
  const r = checkAllowableArea({ occupancyPrimary: "B", constructionType: "V-B", areaSf: 9001 });
  assertEquals(r.status, "fail");
});

Deno.test("allowable area — UL row passes any area", () => {
  const r = checkAllowableArea({ occupancyPrimary: "B", constructionType: "I-A", areaSf: 1_000_000 });
  assertEquals(r.status, "pass");
});

Deno.test("allowable area — NP cell fails outright", () => {
  const r = checkAllowableArea({ occupancyPrimary: "I-2", constructionType: "II-B", areaSf: 1000 });
  assertEquals(r.status, "fail");
});

Deno.test("allowable area — missing inputs return info, never fail", () => {
  const r = checkAllowableArea({ occupancyPrimary: null, constructionType: "V-B", areaSf: 5000 });
  assertEquals(r.status, "info");
});

Deno.test("allowable area — declared occupancy + type but no area is warn (not fail)", () => {
  const r = checkAllowableArea({ occupancyPrimary: "B", constructionType: "V-B", areaSf: null });
  assertEquals(r.status, "warn");
});

// ---------------------------------------------------------------------
// checkAllowableStories  (IBC Table 504.4)
// ---------------------------------------------------------------------
Deno.test("stories — sprinklered B/V-B 2 stories passes (lim 2)", () => {
  const r = checkAllowableStories({
    occupancyPrimary: "B", constructionType: "V-B", storiesAbove: 2, sprinklered: true,
  });
  assertEquals(r.status, "pass");
});

Deno.test("stories — non-sprinklered B/V-B 2 stories fails (lim -> 1)", () => {
  const r = checkAllowableStories({
    occupancyPrimary: "B", constructionType: "V-B", storiesAbove: 2, sprinklered: false,
  });
  assertEquals(r.status, "fail");
});

Deno.test("stories — null sprinklered treated as sprinklered (not penalized)", () => {
  const r = checkAllowableStories({
    occupancyPrimary: "B", constructionType: "V-B", storiesAbove: 2, sprinklered: null,
  });
  assertEquals(r.status, "pass");
});

// ---------------------------------------------------------------------
// requiredMinExits  (IBC 1006.3.2)
// ---------------------------------------------------------------------
Deno.test("required exits — 500 OL needs 2", () => assertEquals(requiredMinExits(500), 2));
Deno.test("required exits — 501 OL needs 3", () => assertEquals(requiredMinExits(501), 3));
Deno.test("required exits — 1000 OL needs 3", () => assertEquals(requiredMinExits(1000), 3));
Deno.test("required exits — 1001 OL needs 4", () => assertEquals(requiredMinExits(1001), 4));
Deno.test("required exits — single occupant still 2 (minimum)", () => assertEquals(requiredMinExits(1), 2));

Deno.test("min exits — OL 600 with 2 declared fails", () => {
  const r = checkMinExits({ occupantLoad: 600, declaredExits: 2 });
  assertEquals(r.status, "fail");
});

Deno.test("min exits — OL 600 with 3 declared passes", () => {
  const r = checkMinExits({ occupantLoad: 600, declaredExits: 3 });
  assertEquals(r.status, "pass");
});

Deno.test("min exits — no OL is info, never fail", () => {
  const r = checkMinExits({ occupantLoad: null, declaredExits: 0 });
  assertEquals(r.status, "info");
});

// ---------------------------------------------------------------------
// checkExitCapacity  (IBC 1005.3)
// ---------------------------------------------------------------------
Deno.test("door capacity — 100 OL needs 20\" doors", () => assertEquals(requiredDoorWidthIn(100), 20));
Deno.test("stair capacity — 100 OL needs 30\" stairs", () => assertEquals(requiredStairWidthIn(100), 30));

Deno.test("exit cap — sufficient door width passes", () => {
  const r = checkExitCapacity({ occupantLoad: 100, declaredDoorWidthIn: 36, declaredStairWidthIn: 0 });
  assertEquals(r.status, "pass");
});

Deno.test("exit cap — insufficient door width fails with concrete number", () => {
  const r = checkExitCapacity({ occupantLoad: 100, declaredDoorWidthIn: 15, declaredStairWidthIn: 0 });
  assertEquals(r.status, "fail");
});

Deno.test("exit cap — zero declared widths is warn, not fail", () => {
  const r = checkExitCapacity({ occupantLoad: 200, declaredDoorWidthIn: 0, declaredStairWidthIn: 0 });
  assertEquals(r.status, "warn");
});

// ---------------------------------------------------------------------
// requiredFixtureCount  (IPC Table 403.1 abbreviated)
// ---------------------------------------------------------------------
Deno.test("fixtures — B 100 OL needs 4 WC / 3 lav", () => {
  assertEquals(requiredFixtureCount("B", 100), { wc: 4, lav: 3 });
});

Deno.test("fixtures — R-2 50 OL needs 5 WC / 5 lav", () => {
  assertEquals(requiredFixtureCount("R-2", 50), { wc: 5, lav: 5 });
});

Deno.test("fixtures — group fallback: A-2 falls back to A ratios", () => {
  assertEquals(requiredFixtureCount("A-2", 150), { wc: 2, lav: 1 });
});

Deno.test("fixtures — fail when actual < required", () => {
  const r = checkFixtures({ occupancyPrimary: "B", occupantLoad: 100, actualWc: 2, actualLav: 2 });
  assertEquals(r.status, "fail");
});

Deno.test("fixtures — pass when actual >= required", () => {
  const r = checkFixtures({ occupancyPrimary: "B", occupantLoad: 100, actualWc: 4, actualLav: 3 });
  assertEquals(r.status, "pass");
});

Deno.test("fixtures — no schedule found is warn, not fail", () => {
  const r = checkFixtures({ occupancyPrimary: "B", occupantLoad: 100, actualWc: null, actualLav: null });
  assertEquals(r.status, "warn");
});

// ---------------------------------------------------------------------
// isHighRise  (IBC 403)
// ---------------------------------------------------------------------
Deno.test("high-rise — 75 ft exactly is NOT high-rise", () => assertEquals(isHighRise(75), false));
Deno.test("high-rise — 75.1 ft IS high-rise", () => assertEquals(isHighRise(75.1), true));
Deno.test("high-rise — null height returns false (cannot evaluate)", () => assertEquals(isHighRise(null), false));
