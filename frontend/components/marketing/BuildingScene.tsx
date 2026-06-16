"use client";

// Procedural 3D scene driven by a scroll progress MotionValue.
//
// Progress timeline (p ∈ [0,1]):
//   0.00–0.18  Top-down parchment blueprint, fully opaque
//   0.18–0.42  Camera tilts to 3/4 view; vertical light beams shoot up at corners
//   0.42–0.65  Glass building extrudes from footprint, walls become translucent
//   0.55–0.88  Blueprint fades; a surrounding city rises in (concrete ground +
//              staggered buildings, taller toward the back for a skyline)
//   0.85–1.00  Building fully solid; scene reaches final stable composition
//
// The scene reads progress every frame via .get() on the MotionValue, so React
// never re-renders on scroll — only the GPU does work.
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { Edges, Environment, Lightformer, ContactShadows } from "@react-three/drei";
import { useEffect, useMemo, useRef } from "react";
import * as THREE from "three";
import type { MotionValue } from "framer-motion";

// ────────────────────────────── helpers ──────────────────────────────

const lerp = (a: number, b: number, t: number) => a + (b - a) * t;
const clamp01 = (x: number) => Math.max(0, Math.min(1, x));
const smoothstep = (e0: number, e1: number, x: number) => {
  const t = clamp01((x - e0) / (e1 - e0));
  return t * t * (3 - 2 * t);
};

// ────────────────── Slender glass tower (single source of truth) ───────────────
// A clean, classical supertall: a slender stack of floor-by-floor glass plates,
// each glass band capped by a thin concrete slab edge — the horizontal floor
// lines that make it read as real stacked floors. NO cantilevers/offsets: a
// straight, elegant shaft with just a whisper of taper and a slightly inset
// crown cap. World units are meters-ish.
const FLOOR_H = 0.45;          // story height
const N_FLOORS = 42;           // tower height in floors
// Footprint matches the building outline on the blueprint plan (~48'+48' wide ×
// ~39'+39' deep on the 14×10 plan sheet), so the extruded tower fills the plate.
const TOWER_W = 7.8;           // base plate width  (E–W)
const TOWER_D = 6.5;           // base plate depth  (N–S)
const PODIUM_W = 8.8;
const PODIUM_D = 7.4;
const PODIUM_H = 1.6;          // plaza level the shaft rises from
const GLASS_FRAC = 0.93;       // glass band height as a fraction of the floor (thin floor lines)
const TOWER_TOP = PODIUM_H + N_FLOORS * FLOOR_H;

type Floor = { i: number; baseY: number; x: number; z: number; w: number; d: number };

// Per-floor plate size. Aligned, straight tower — no lateral offsets. A gentle
// taper up the shaft plus a slightly inset crown cap keep it from reading as a
// plain extruded box while staying classical and "normal."
function floorOffset(i: number, n: number): { x: number; z: number; w: number; d: number } {
  const frac = i / (n - 1);
  let s = lerp(1.0, 0.9, frac * frac);   // whisper of taper toward the top
  if (frac > 0.93) s *= 0.9;             // small inset mechanical crown cap
  return { x: 0, z: 0, w: TOWER_W * s, d: TOWER_D * s };
}

const FLOORS: Floor[] = Array.from({ length: N_FLOORS }, (_, i) => {
  const o = floorOffset(i, N_FLOORS);
  return { i, baseY: PODIUM_H + i * FLOOR_H, x: o.x, z: o.z, w: o.w, d: o.d };
});

// The four podium footprint corners — where the holographic beams originate.
const FOOTPRINT_CORNERS = [[-1, -1], [1, -1], [1, 1], [-1, 1]].map(([sx, sz]) => ({
  x: (sx * PODIUM_W) / 2,
  z: (sz * PODIUM_D) / 2,
}));

// ────────────────── Blueprint texture (procedural canvas) ────────────────────

function createBlueprintTexture(): THREE.CanvasTexture {
  const W = 1024, H = 768;
  const canvas = document.createElement("canvas");
  canvas.width = W; canvas.height = H;
  const ctx = canvas.getContext("2d")!;

  // Sheet — pure white; black ink + a black border are drawn on top below
  ctx.fillStyle = "#FFFFFF";
  ctx.fillRect(0, 0, W, H);

  // Double border — solid black
  ctx.strokeStyle = "#000000";
  ctx.lineWidth = 2;
  ctx.strokeRect(40, 40, W - 80, H - 80);
  ctx.lineWidth = 1;
  ctx.strokeRect(52, 52, W - 104, H - 104);

  // Title block — black
  ctx.fillStyle = "#000000";
  ctx.font = 'bold 24px "Inter", system-ui, sans-serif';
  ctx.textAlign = "center";
  ctx.fillText("RESIDENTIAL TOWER — TYPICAL FLOOR PLAN", W / 2, 92);
  ctx.font = '11px "DM Mono", monospace';
  ctx.fillText("SHEET: A2.01   ·   SCALE 1:200   ·   23-STORY TOWER   ·   ARCHITECHTURA PLAN REVIEW", W / 2, 112);

  // Subtle grid — light grey
  ctx.strokeStyle = "rgba(0, 0, 0, 0.08)";
  ctx.lineWidth = 0.5;
  for (let x = 64; x < W - 64; x += 32) {
    ctx.beginPath(); ctx.moveTo(x, 140); ctx.lineTo(x, H - 60); ctx.stroke();
  }
  for (let y = 144; y < H - 60; y += 32) {
    ctx.beginPath(); ctx.moveTo(64, y); ctx.lineTo(W - 64, y); ctx.stroke();
  }

  // ───────────────── Detailed residential floor plate (canvas px) ───────────
  // A luxury full-floor plate drawn directly in canvas pixels: a chamfered,
  // articulated perimeter; a dense central core (3 elevators + 2 egress stairs
  // + service shafts) wrapped by a corridor ring; and four corner residences
  // with kitchens, baths and bedrooms — detailed enough to read as a real sheet.
  const L = 215, T = 178, R = 812, B = 702;
  const MX = (L + R) / 2, MY = (T + B) / 2;
  const ch = 44;   // perimeter corner chamfer
  const iw = 7;    // exterior wall cavity (double-line)

  // ── drawing helpers ──
  const poly = (pts: number[][], close = false) => {
    ctx.beginPath();
    pts.forEach(([x, y], i) => (i ? ctx.lineTo(x, y) : ctx.moveTo(x, y)));
    if (close) ctx.closePath();
    ctx.stroke();
  };
  const seg = (x1: number, y1: number, x2: number, y2: number) => poly([[x1, y1], [x2, y2]]);
  const sq = (x: number, y: number, s: number) => ctx.fillRect(x - s / 2, y - s / 2, s, s);
  const tub = (x: number, y: number, w: number, h: number) => {
    ctx.strokeRect(x, y, w, h);
    ctx.beginPath(); ctx.ellipse(x + w / 2, y + h / 2, w / 2 - 4, h / 2 - 4, 0, 0, Math.PI * 2); ctx.stroke();
  };
  const wc = (x: number, y: number) => {
    ctx.strokeRect(x, y, 12, 7);
    ctx.beginPath(); ctx.ellipse(x + 6, y + 14, 7, 9, 0, 0, Math.PI * 2); ctx.stroke();
  };
  const basin = (x: number, y: number, w = 18, h = 11) => {
    ctx.strokeRect(x, y, w, h);
    ctx.beginPath(); ctx.ellipse(x + w / 2, y + h / 2, w / 2 - 3, h / 2 - 3, 0, 0, Math.PI * 2); ctx.stroke();
  };
  const stair = (sx: number, sy: number, sw: number, sh: number, n: number) => {
    ctx.strokeRect(sx, sy, sw, sh);
    for (let i = 1; i < n; i++) seg(sx, sy + (sh / n) * i, sx + sw, sy + (sh / n) * i);
    seg(sx + sw / 2, sy, sx + sw / 2, sy + sh);
  };
  const shaft = (x: number, y: number, s: number) => { ctx.strokeRect(x, y, s, s); seg(x, y, x + s, y + s); };

  // ── Structural grid: faint lines + lettered/numbered bubbles + columns ──
  const gx = [L + 96, L + 232, MX, R - 232, R - 96];
  const gy = [T + 86, MY - 56, MY + 56, B - 86];
  ctx.strokeStyle = "rgba(0,0,0,0.16)"; ctx.lineWidth = 0.6;
  gx.forEach((x) => seg(x, T - 30, x, B + 6));
  gy.forEach((y) => seg(L - 30, y, R + 6, y));
  ctx.strokeStyle = "#000000"; ctx.fillStyle = "#000000"; ctx.lineWidth = 0.8;
  ctx.textAlign = "center"; ctx.textBaseline = "middle"; ctx.font = '9px "DM Mono", monospace';
  gx.forEach((x, i) => { ctx.beginPath(); ctx.arc(x, T - 40, 9, 0, Math.PI * 2); ctx.stroke(); ctx.fillText(String.fromCharCode(65 + i), x, T - 40); });
  gy.forEach((y, i) => { ctx.beginPath(); ctx.arc(L - 40, y, 9, 0, Math.PI * 2); ctx.stroke(); ctx.fillText(String(i + 1), L - 40, y); });
  ctx.textBaseline = "alphabetic";
  gx.forEach((x) => gy.forEach((y) => sq(x, y, 8)));

  // ── Exterior wall — chamfered perimeter, drawn as a double line ──
  ctx.strokeStyle = "#000000"; ctx.lineWidth = 4.5;
  poly([[L + ch, T], [R - ch, T], [R, T + ch], [R, B - ch], [R - ch, B], [L + ch, B], [L, B - ch], [L, T + ch]], true);
  ctx.lineWidth = 1;
  const cc = ch - iw * 0.5;
  poly([[L + iw + cc, T + iw], [R - iw - cc, T + iw], [R - iw, T + iw + cc], [R - iw, B - iw - cc], [R - iw - cc, B - iw], [L + iw + cc, B - iw], [L + iw, B - iw - cc], [L + iw, T + iw + cc]], true);

  // ── Central core: corridor ring, walls, elevators, stairs, shafts ──
  const cL = MX - 104, cR = MX + 104, cT = MY - 88, cB = MY + 88;
  ctx.strokeStyle = "rgba(0,0,0,0.4)"; ctx.lineWidth = 1;
  ctx.strokeRect(cL - 30, cT - 30, (cR - cL) + 60, (cB - cT) + 60);
  ctx.strokeStyle = "#000000"; ctx.lineWidth = 2.6;
  ctx.strokeRect(cL, cT, cR - cL, cB - cT);
  ctx.strokeStyle = "rgba(0,0,0,0.7)"; ctx.lineWidth = 1;
  seg(cL, MY, cR, MY);
  // elevators (3 cabs, upper core, each with an X)
  const bank = (cR - cL) - 16;
  for (let i = 0; i < 3; i++) {
    const ew = bank / 3 - 5, ex = cL + 8 + i * (bank / 3);
    ctx.strokeRect(ex, cT + 10, ew, 58);
    seg(ex, cT + 10, ex + ew, cT + 68); seg(ex + ew, cT + 10, ex, cT + 68);
  }
  // egress stairs (lower core)
  stair(cL + 8, MY + 14, 60, 62, 9);
  stair(cR - 68, MY + 14, 60, 62, 9);
  // service shafts between the stairs
  shaft(MX - 18, MY + 22, 15); shaft(MX + 3, MY + 22, 15);
  shaft(MX - 18, MY + 46, 15); shaft(MX + 3, MY + 46, 15);

  // ── Demising walls — split the perimeter ring into four residences ──
  ctx.strokeStyle = "#000000"; ctx.lineWidth = 1.8;
  seg(MX, T + iw, MX, cT - 30); seg(MX, cB + 30, MX, B - iw);
  seg(L + iw, MY, cL - 30, MY); seg(cR + 30, MY, R - iw, MY);

  // ── Interior partitions (bedroom / kitchen separations) ──
  ctx.strokeStyle = "rgba(0,0,0,0.6)"; ctx.lineWidth = 1.1;
  seg(L + iw, T + 138, cL - 30, T + 138); seg(R - iw, T + 138, cR + 30, T + 138);
  seg(L + iw, B - 138, cL - 30, B - 138); seg(R - iw, B - 138, cR + 30, B - 138);
  seg(L + 150, T + iw, L + 150, T + 138); seg(R - 150, T + iw, R - 150, T + 138);
  seg(L + 150, B - 138, L + 150, B - iw); seg(R - 150, B - 138, R - 150, B - iw);

  // ── Fixtures: bathrooms beside the core + kitchen islands ──
  ctx.strokeStyle = "rgba(0,0,0,0.78)"; ctx.lineWidth = 1.1;
  tub(cL - 100, cT + 2, 62, 28);  wc(cL - 116, cT + 2);  basin(cL - 118, cT + 32);
  tub(cR + 38,  cT + 2, 62, 28);  wc(cR + 100, cT + 2);  basin(cR + 100, cT + 32);
  tub(cL - 100, cB - 30, 62, 28); wc(cL - 116, cB - 6);  basin(cL - 118, cB - 40);
  tub(cR + 38,  cB - 30, 62, 28); wc(cR + 100, cB - 6);  basin(cR + 100, cB - 40);
  ctx.lineWidth = 1.2;
  ctx.strokeRect(L + 64, T + 62, 92, 26); ctx.strokeRect(R - 156, T + 62, 92, 26);
  ctx.strokeRect(L + 64, B - 88, 92, 26); ctx.strokeRect(R - 156, B - 88, 92, 26);

  // ── Overall dimension string (top) ──
  ctx.strokeStyle = "#000000"; ctx.lineWidth = 1; ctx.fillStyle = "#000000";
  ctx.font = '10px "DM Mono", monospace'; ctx.textAlign = "center";
  const dY = T - 16;
  seg(L, dY, R, dY);
  [L, MX, R].forEach((x) => seg(x, dY - 4, x, dY + 4));
  ctx.fillText('48\'-0"', (L + MX) / 2, dY - 6);
  ctx.fillText('48\'-0"', (MX + R) / 2, dY - 6);

  // ── Room labels ──
  ctx.fillStyle = "rgba(0,0,0,0.6)"; ctx.font = '9px "DM Mono", monospace'; ctx.textAlign = "center";
  ctx.fillText("RESIDENCE A", L + 132, T + 116);
  ctx.fillText("RESIDENCE B", R - 132, T + 116);
  ctx.fillText("RESIDENCE C", L + 132, B - 108);
  ctx.fillText("RESIDENCE D", R - 132, B - 108);
  ctx.fillText("ELEV. LOBBY", MX, cT - 12);
  ctx.font = '8px "DM Mono", monospace'; ctx.fillStyle = "rgba(0,0,0,0.5)";
  ctx.fillText("STAIR 1", cL + 38, MY + 84); ctx.fillText("STAIR 2", cR - 38, MY + 84);

  // ─────────────── M/E/P overlay — subtle navy (mech / elec / plumb) ────────
  const navy = "rgba(26, 52, 104, 0.7)";
  ctx.strokeStyle = navy;
  // Mechanical: supply-air trunk-duct loop around the core (double line)
  ctx.lineWidth = 2;
  const dl = cL - 50, dr = cR + 50, dt = cT - 50, db = cB + 50;
  ctx.strokeRect(dl, dt, dr - dl, db - dt);
  ctx.lineWidth = 0.8;
  ctx.strokeRect(dl + 5, dt + 5, dr - dl - 10, db - dt - 10);
  // branch ducts out to each residence, ending in a ceiling diffuser
  const diffuser = (x: number, y: number) => {
    ctx.strokeRect(x - 7, y - 7, 14, 14);
    seg(x - 7, y - 7, x + 7, y + 7); seg(x + 7, y - 7, x - 7, y + 7);
  };
  ctx.lineWidth = 1.4;
  [[-1, -1], [1, -1], [-1, 1], [1, 1]].forEach(([sx, sy]) => {
    const bx = MX + sx * 150, by = MY + sy * 108;
    seg(MX + sx * 56, MY + sy * 56, bx, by);
    diffuser(bx, by);
  });
  // Plumbing: stacked risers (circle + slash) at the wet walls
  ctx.lineWidth = 1.1;
  const riser = (x: number, y: number) => { ctx.beginPath(); ctx.arc(x, y, 5, 0, Math.PI * 2); ctx.stroke(); seg(x - 3.5, y - 3.5, x + 3.5, y + 3.5); };
  [[cL - 30, cT + 14], [cR + 30, cT + 14], [cL - 30, cB - 14], [cR + 30, cB - 14],
   [L + 116, T + 78], [R - 116, T + 78], [L + 116, B - 78], [R - 116, B - 78]].forEach(([x, y]) => riser(x, y));
  // Electrical: light fixtures (circle + cross) + a panel on the core wall
  const light = (x: number, y: number) => { ctx.beginPath(); ctx.arc(x, y, 5, 0, Math.PI * 2); ctx.stroke(); seg(x - 5, y, x + 5, y); seg(x, y - 5, x, y + 5); };
  [[-1.7, -1], [1.7, -1], [-1.7, 1], [1.7, 1]].forEach(([sx, sy]) => light(MX + sx * 86, MY + sy * 92));
  ctx.lineWidth = 1.2; ctx.strokeRect(cR + 2, cT + 28, 9, 22); seg(cR + 2, cT + 28, cR + 11, cT + 50);

  // ─────────────── Layered dimension strings (left margin) ──────────────────
  ctx.strokeStyle = "#000000"; ctx.fillStyle = "#000000"; ctx.font = '9px "DM Mono", monospace';
  ctx.lineWidth = 1; const dXo = 150;            // outer: overall depth
  seg(dXo, T, dXo, B); [T, MY, B].forEach((y) => seg(dXo - 4, y, dXo + 4, y));
  [(T + MY) / 2, (MY + B) / 2].forEach((yy) => { ctx.save(); ctx.translate(dXo - 8, yy); ctx.rotate(-Math.PI / 2); ctx.textAlign = "center"; ctx.fillText('39\'-0"', 0, 0); ctx.restore(); });
  ctx.lineWidth = 0.9; const dXi = 196;          // inner: bay dims, ticked to grid
  seg(dXi, T, dXi, B); [T, ...gy, B].forEach((y) => seg(dXi - 3, y, dXi + 3, y));

  // ─────────────── Section callout — dash-dot cut line + bugs ───────────────
  ctx.strokeStyle = "#000000"; ctx.lineWidth = 1.2;
  ctx.setLineDash([12, 4, 3, 4]);
  const secY = T + 152;
  seg(206, secY, 802, secY);
  ctx.setLineDash([]);
  const bug = (x: number, y: number, n: string, sheet: string) => {
    ctx.beginPath(); ctx.arc(x, y, 12, 0, Math.PI * 2); ctx.stroke(); seg(x - 12, y, x + 12, y);
    ctx.fillStyle = "#000000"; ctx.textAlign = "center";
    ctx.font = 'bold 9px "DM Mono", monospace'; ctx.fillText(n, x, y - 2);
    ctx.font = '7px "DM Mono", monospace'; ctx.fillText(sheet, x, y + 9);
  };
  bug(206, secY, "A", "A4"); bug(802, secY, "A", "A4");

  // ─────────────── Spot elevations ───────────────
  const spot = (x: number, y: number, t: string) => {
    ctx.strokeStyle = "#000000"; ctx.lineWidth = 1;
    seg(x - 6, y, x + 6, y); seg(x, y - 6, x, y + 6);
    ctx.beginPath(); ctx.moveTo(x, y + 2); ctx.lineTo(x - 5, y + 11); ctx.lineTo(x + 5, y + 11); ctx.closePath(); ctx.stroke();
    ctx.fillStyle = "rgba(0,0,0,0.7)"; ctx.font = '7px "DM Mono", monospace'; ctx.textAlign = "left"; ctx.fillText(t, x + 9, y + 2);
  };
  spot(L + 150, B - 150, 'FFL +312\'-6"'); spot(R - 150, T + 200, 'FFL +312\'-6"');

  // ─────────────── Title block (right edge) ───────────────
  const tbX = 822, tbW = 146, tbY = 286, tbH = 418;
  ctx.strokeStyle = "#000000"; ctx.lineWidth = 1.5;
  ctx.strokeRect(tbX, tbY, tbW, tbH);
  ctx.lineWidth = 0.8;
  [tbY + 70, tbY + 110, tbY + 150, tbY + 190, tbY + 300].forEach((y) => seg(tbX, y, tbX + tbW, y));
  // north arrow (top cell)
  ctx.save(); ctx.translate(tbX + tbW / 2, tbY + 42); ctx.strokeStyle = "#000000"; ctx.lineWidth = 1.5;
  ctx.beginPath(); ctx.moveTo(0, -16); ctx.lineTo(-7, 8); ctx.lineTo(0, 3); ctx.lineTo(7, 8); ctx.closePath(); ctx.stroke();
  ctx.fillStyle = "#000000"; ctx.font = 'bold 10px "DM Mono", monospace'; ctx.textAlign = "center"; ctx.fillText("N", 0, -22);
  ctx.restore();
  // fields
  const fld = (y: number, label: string, value: string, vFont = '9px "DM Mono", monospace', vx = tbX + 8) => {
    ctx.textAlign = "left";
    ctx.fillStyle = "rgba(0,0,0,0.5)"; ctx.font = '7px "DM Mono", monospace'; ctx.fillText(label, vx, y);
    ctx.fillStyle = "#000000"; ctx.font = vFont; ctx.fillText(value, vx, y + 13);
  };
  fld(tbY + 84, "PROJECT", "MIXED-USE TOWER");
  fld(tbY + 124, "SHEET TITLE", "TYPICAL FLOOR PLAN");
  fld(tbY + 164, "SCALE", "1:200");
  fld(tbY + 164, "DATE", "2026-06-14", '9px "DM Mono", monospace', tbX + 78);
  ctx.textAlign = "left"; ctx.fillStyle = "rgba(0,0,0,0.5)"; ctx.font = '7px "DM Mono", monospace';
  ctx.fillText("REV DATE    DESCRIPTION", tbX + 8, tbY + 206);
  ctx.fillStyle = "rgba(0,0,0,0.72)";
  ctx.fillText("01  06-06  ISSUED FOR REVIEW", tbX + 8, tbY + 220);
  ctx.fillText("02  06-14  M/E/P COORDINATION", tbX + 8, tbY + 232);
  ctx.fillText("03  06-14  HYPER-DETAIL SET", tbX + 8, tbY + 244);
  ctx.textAlign = "center";
  ctx.fillStyle = "#000000"; ctx.font = 'bold 14px "Inter", sans-serif'; ctx.fillText("Architechtura", tbX + tbW / 2, tbY + 326);
  ctx.fillStyle = "rgba(0,0,0,0.5)"; ctx.font = '7px "DM Mono", monospace'; ctx.fillText("SHEET", tbX + tbW / 2, tbY + 346);
  ctx.fillStyle = "#000000"; ctx.font = 'bold 34px "Inter", sans-serif'; ctx.fillText("A2.01", tbX + tbW / 2, tbY + 390);

  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.anisotropy = 8;
  texture.needsUpdate = true;
  return texture;
}

// ────────────────── City ground texture (tileable street grid) ────────────────

function createCityGroundTexture(): THREE.CanvasTexture {
  const S = 256;
  const canvas = document.createElement("canvas");
  canvas.width = S; canvas.height = S;
  const ctx = canvas.getContext("2d")!;

  // Asphalt road base
  ctx.fillStyle = "#C7CDD5";
  ctx.fillRect(0, 0, S, S);
  // Lighter city block (lot) inset within the tile
  ctx.fillStyle = "#DDE1E7";
  ctx.fillRect(22, 22, S - 44, S - 44);
  // Faint lane dashes along the two road edges of the tile
  ctx.strokeStyle = "rgba(255, 255, 255, 0.45)";
  ctx.lineWidth = 2;
  ctx.setLineDash([12, 12]);
  ctx.beginPath();
  ctx.moveTo(11, 0); ctx.lineTo(11, S);
  ctx.moveTo(0, 11); ctx.lineTo(S, 11);
  ctx.stroke();

  const texture = new THREE.CanvasTexture(canvas);
  texture.wrapS = texture.wrapT = THREE.RepeatWrapping;
  texture.repeat.set(20, 20); // 200u plane / 20 = one 10u city block per tile
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.anisotropy = 8;
  texture.needsUpdate = true;
  return texture;
}

// ────────────────── Curtain-wall facade texture (city buildings) ───────────────
// A light, tintable glass-office facade: stacked floor bands (spandrel lines +
// glass), vertical mullions and a window grid. Drawn light so each building's
// material `color` tints it to a muted grey/cream/taupe. One shared texture
// gives every surrounding building the same floor-by-floor detail as the hero
// without thousands of meshes.
function createFacadeTexture(): THREE.CanvasTexture {
  const W = 256, H = 512;
  const canvas = document.createElement("canvas");
  canvas.width = W; canvas.height = H;
  const ctx = canvas.getContext("2d")!;

  // Light base with a faint vertical sheen so glass reads top-lit
  const g = ctx.createLinearGradient(0, 0, 0, H);
  g.addColorStop(0, "#fbfcfe");
  g.addColorStop(0.5, "#eef1f6");
  g.addColorStop(1, "#f4f6f9");
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, W, H);

  const floors = 18;          // floor bands down the texture
  const cols = 9;             // window columns
  const fh = H / floors, cw = W / cols;

  // Window panes — subtle per-pane tonal variation for life
  for (let r = 0; r < floors; r++) {
    for (let c = 0; c < cols; c++) {
      const v = ((r * 7 + c * 13) % 5) / 5;           // deterministic 0..0.8
      ctx.fillStyle = `rgba(${150 + v * 40 | 0}, ${165 + v * 40 | 0}, ${185 + v * 35 | 0}, ${0.10 + v * 0.10})`;
      ctx.fillRect(c * cw + 1.5, r * fh + 2.5, cw - 3, fh - 4);
    }
  }
  // Floor spandrel lines (the strong horizontal read)
  ctx.fillStyle = "rgba(40, 50, 66, 0.20)";
  for (let r = 0; r <= floors; r++) ctx.fillRect(0, r * fh - 1, W, 2);
  // Vertical mullions (lighter)
  ctx.fillStyle = "rgba(40, 50, 66, 0.10)";
  for (let c = 0; c <= cols; c++) ctx.fillRect(c * cw - 0.5, 0, 1, H);

  const texture = new THREE.CanvasTexture(canvas);
  texture.wrapS = texture.wrapT = THREE.ClampToEdgeWrapping;
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.anisotropy = 8;
  texture.needsUpdate = true;
  return texture;
}

// ────────────────── Scene contents (inside Canvas) ────────────────────────────

function SceneContents({ progress }: { progress: MotionValue<number> }) {
  const { scene, camera, gl } = useThree();

  // ─── Blueprint plane ───
  const blueprintTex = useMemo(() => createBlueprintTexture(), []);
  useEffect(() => () => blueprintTex.dispose(), [blueprintTex]);

  const blueprintRef = useRef<THREE.Mesh>(null);
  const blueprintMat = useRef<THREE.MeshBasicMaterial>(null);

  // ─── Beams (one per podium footprint corner) ───
  // Holographic beams shoot up from the plan footprint corners to the full
  // height of the finished tower, tracing the volume before it fills in.
  const beamPositions = useMemo(
    () => FOOTPRINT_CORNERS.map((c, i) => ({ x: c.x, z: c.z, h: TOWER_TOP, key: `beam-${i}` })),
    []
  );
  const beamRefs = useRef<(THREE.Mesh | null)[]>([]);

  // ─── Building: one group per floor (glass plate + concrete slab edge) ───
  const floorRefs = useRef<(THREE.Group | null)[]>([]);
  const podiumRef = useRef<THREE.Group>(null);
  const beanRef = useRef<THREE.Group>(null);

  // ─── City context ───
  const groundMat = useRef<THREE.MeshStandardMaterial>(null);
  const cityRefs = useRef<(THREE.Mesh | null)[]>([]);
  const propsRef = useRef<THREE.Group>(null);   // trees / people / cars

  // Tileable street-grid ground texture
  const groundTex = useMemo(() => createCityGroundTexture(), []);
  useEffect(() => () => groundTex.dispose(), [groundTex]);

  // Shared glass-facade texture for the surrounding city buildings
  const facadeTex = useMemo(() => createFacadeTexture(), []);
  useEffect(() => () => facadeTex.dispose(), [facadeTex]);

  // ─── Scene fog/background ───
  // Pure WHITE. NOTE: a scene.background Color gets darkened to grey by the
  // renderer's ACES tone mapping — that was the grey start screen. Using the
  // raw clear color (NOT tone-mapped) and leaving background null guarantees a
  // truly white page behind everything. Fog (also white) fades the far city.
  const fog = useMemo(() => new THREE.Fog("#FFFFFF", 38, 82), []);
  useEffect(() => {
    scene.fog = fog;
    scene.background = null;
    gl.setClearColor(new THREE.Color("#FFFFFF"), 1);
    return () => { scene.fog = null; };
  }, [scene, fog, gl]);

  useFrame(() => {
    const p = progress.get();

    // ─── Camera path: high-angle drafting view → 3/4 view ───
    // Start pulled WAY back and looking at a point ahead of the plan so the
    // sheet sits in the LOWER half of the viewport — leaves the top half for
    // the tagline. End farther back / higher so the 22u tall highrise reads.
    const camT = smoothstep(0.05, 0.55, p);
    camera.position.x = lerp(0,  24, camT);
    camera.position.y = lerp(26, 15, camT);
    camera.position.z = lerp(6,  30, camT);
    // Same close, low 3/4 angle as the live site — just enough distance for the
    // now-wider (plan-matching) tower to fill the frame, top near the edge.
    // Looking at a point ahead of the plan keeps the sheet low early.
    camera.lookAt(0, lerp(0, 8.5, camT), lerp(-3.5, 0, camT));

    // ─── Fog stays pure WHITE — the far city dissolves into a clean white
    // haze for depth; the tower + near city stay crisp. Background is the white
    // clear color set once (above), untouched by tone mapping.
    const sceneT = smoothstep(0.55, 0.85, p);
    fog.color.set("#FFFFFF");
    fog.near = lerp(40, 36, sceneT);
    fog.far  = lerp(86, 76, sceneT);

    // ─── Blueprint plane: fully opaque until building takes over ───
    if (blueprintMat.current) {
      blueprintMat.current.opacity = lerp(1, 0, smoothstep(0.55, 0.78, p));
      blueprintMat.current.transparent = true;
    }

    // ─── Light beams: extrude then dim ───
    const beamUp   = smoothstep(0.15, 0.42, p);
    const beamFade = smoothstep(0.55, 0.78, p);
    beamRefs.current.forEach((m, i) => {
      if (!m) return;
      const targetH = beamPositions[i].h;
      m.scale.y = Math.max(0.0001, beamUp * targetH);
      m.position.y = m.scale.y / 2;
      const mat = m.material as THREE.MeshStandardMaterial;
      mat.opacity = (0.85 - beamFade * 0.85) * (beamUp);
      mat.emissiveIntensity = lerp(2.5, 0.0, beamFade);
    });

    // ─── Tower: floors rise bottom-to-top like real construction ───
    // Each floor plate pops up from its base in sequence — lowest floors form
    // first (~0.34), the cantilevered crown last (~0.86) — so the tower visibly
    // builds itself as you scroll instead of materializing all at once.
    const RISE_LO = 0.34, RISE_HI = 0.86, RISE_WIN = 0.14;
    if (podiumRef.current) {
      const t = smoothstep(RISE_LO - 0.05, RISE_LO + 0.09, p);
      podiumRef.current.visible = t > 0.001;
      podiumRef.current.scale.y = Math.max(0.0001, t);
    }
    floorRefs.current.forEach((g, i) => {
      if (!g) return;
      const frac = FLOORS[i].baseY / TOWER_TOP;           // 0..1 up the tower
      const start = lerp(RISE_LO, RISE_HI - RISE_WIN, frac);
      const t = smoothstep(start, start + RISE_WIN, p);
      g.visible = t > 0.001;
      g.scale.y = Math.max(0.0001, t);
      // Ease each plate up from just below its resting height for a soft pop.
      g.position.y = FLOORS[i].baseY - (1 - t) * 0.22;
    });
    // Anish Kapoor mirror "bean" settles into the plaza once the tower stands.
    if (beanRef.current) {
      const t = smoothstep(0.7, 0.86, p);
      beanRef.current.visible = t > 0.001;
      beanRef.current.scale.setScalar(Math.max(0.0001, t));
    }

    // ─── City context: ground fades in, buildings rise + fade in waves ───
    const landT = smoothstep(0.55, 0.88, p);
    if (groundMat.current) {
      groundMat.current.opacity = landT;
      groundMat.current.transparent = true;
    }
    cityRefs.current.forEach((m, i) => {
      if (!m) return;
      const b = cityBuildings[i];
      // Per-building stagger: `delay` (0..1) shifts the rise window so the
      // skyline materializes in waves rather than all at once.
      const start = 0.52 + b.delay * 0.26;
      const t = smoothstep(start, start + 0.16, p);
      const sy = Math.max(0.0001, t);
      m.scale.y = sy;                    // extrude from the ground
      m.position.y = (b.h * sy) / 2;
      m.traverse((o) => {
        const mat = (o as THREE.Mesh).material as
          | (THREE.Material & { opacity: number })
          | undefined;
        if (mat && "opacity" in mat) { mat.transparent = true; mat.opacity = t; }
      });
    });

    // Street props (trees / people / cars) appear once the city ground is in.
    if (propsRef.current) propsRef.current.visible = landT > 0.02;
  });

  // ─── Surrounding city buildings ───
  // Scatter on a jittered grid around the hero — denser and wider than before
  // for a real skyline. Skip the hero footprint and the camera→hero foreground
  // sightline. Taller toward the back. Muted greys / cremes / taupes so the
  // blue hero tower stays the star. Each carries a `delay` for staggered rise.
  const cityBuildings = useMemo(() => {
    const rand = mulberry32(7);
    // Live-site palette — blue-grey glass + light concrete + slate (tints the facade)
    const MUTED = [
      "#C9D8EE", "#BFD2EC", "#D3E0F2", "#AFC6E4",   // blue-grey glass
      "#D9DDE3", "#CFD4DB", "#E2E5EA", "#C7CDD5",   // light concrete
      "#B9C2CD", "#AAB6C4",                          // slate
    ];
    const out: {
      x: number; z: number; w: number; d: number; h: number;
      color: string; glassy: boolean; delay: number;
    }[] = [];
    for (let gx = -36; gx <= 36; gx += 5.4) {
      for (let gz = -44; gz <= 10; gz += 5.4) {
        const x = gx + (rand() - 0.5) * 2.8;
        const z = gz + (rand() - 0.5) * 2.8;
        // Keep the hero footprint clear (with margin)
        if (Math.abs(x) < 7 && z > -5.5 && z < 5.5) continue;
        // Keep the camera→hero foreground sightline clear
        if (z > 2.5 && Math.abs(x) < 9) continue;
        // A few random gaps so it doesn't read as a perfect grid
        if (rand() < 0.14) continue;
        const w = 2.2 + rand() * 3.2;
        const d = 2.2 + rand() * 3.2;
        const depth = clamp01((10 - z) / 54);          // 0 near .. 1 far back
        const h = lerp(2.6, 12.0, depth) * (0.7 + rand() * 0.7);
        const glassy = rand() > 0.4;                   // glassy vs more matte stone
        const color = MUTED[Math.floor(rand() * MUTED.length)];
        out.push({ x, z, w, d, h, color, glassy, delay: rand() });
      }
    }
    return out;
  }, []);

  // ─── Street life — trees, little people, cars (the polished axonometric vibe) ───
  // Scattered in open ground only: never under the hero footprint or a building.
  const streetProps = useMemo(() => {
    const rand = mulberry32(23);
    const clear = (x: number, z: number, pad: number) => {
      if (Math.abs(x) < PODIUM_W / 2 + pad + 0.6 && Math.abs(z) < PODIUM_D / 2 + pad + 0.6) return false;
      for (const b of cityBuildings) {
        if (Math.abs(x - b.x) < b.w / 2 + pad && Math.abs(z - b.z) < b.d / 2 + pad) return false;
      }
      return true;
    };
    const trees: { x: number; z: number; s: number; tone: string }[] = [];
    const people: { x: number; z: number; rot: number; tone: string }[] = [];
    const cars: { x: number; z: number; rot: number; color: string }[] = [];
    const GREENS = ["#7f9b6e", "#8aa178", "#74925f", "#94a886"];
    const SKIN = ["#5a6b86", "#6b7790", "#4f5d77", "#7a86a0"];
    const CARC = ["#cfd4db", "#b9c2cd", "#aab6c4", "#d3d7dd", "#9fb0c8"];
    let g = 0;
    while (trees.length < 48 && g++ < 800) {
      const x = (rand() * 2 - 1) * 30, z = -40 + rand() * 50;
      if (z > 4 && Math.abs(x) < 8) continue;             // keep the foreground sightline
      if (!clear(x, z, 1.1)) continue;
      trees.push({ x, z, s: 0.7 + rand() * 0.8, tone: GREENS[Math.floor(rand() * GREENS.length)] });
    }
    let pp = 0;
    while (people.length < 16 && pp++ < 400) {
      const ang = rand() * Math.PI * 2, r = 3.4 + rand() * 6;
      const x = Math.cos(ang) * r, z = Math.sin(ang) * r;
      if (z > 4 && Math.abs(x) < 7) continue;
      if (!clear(x, z, 0.5)) continue;
      people.push({ x, z, rot: rand() * Math.PI * 2, tone: SKIN[Math.floor(rand() * SKIN.length)] });
    }
    let cc = 0;
    while (cars.length < 10 && cc++ < 400) {
      const x = (rand() * 2 - 1) * 24, z = -34 + rand() * 42;
      if (z > 4 && Math.abs(x) < 8) continue;
      if (!clear(x, z, 1.6)) continue;
      cars.push({ x, z, rot: rand() < 0.5 ? 0 : Math.PI / 2, color: CARC[Math.floor(rand() * CARC.length)] });
    }
    return { trees, people, cars };
  }, [cityBuildings]);

  return (
    <>
      {/* Lights — soft key for slab/cantilever definition; the Environment
          below does most of the fill and ALL the glass reflections. */}
      <ambientLight intensity={0.32} color="#FBFCFF" />
      <hemisphereLight color="#EAF1FB" groundColor="#C2C9D4" intensity={0.5} />
      <directionalLight
        position={[12, 22, 9]}
        intensity={1.05}
        color="#FFF6E8"
        castShadow
        shadow-mapSize={[2048, 2048]}
        shadow-camera-left={-22}
        shadow-camera-right={22}
        shadow-camera-top={30}
        shadow-camera-bottom={-6}
        shadow-bias={-0.0004}
        shadow-normalBias={0.02}
      />

      {/* Image-based environment — built procedurally from Lightformers (no
          network fetch, no asset weight). The bright sky card + warm/cool side
          panels + vertical "reflected-city" streaks are what the glass curtain
          wall mirrors, turning flat boxes into believable glass. */}
      <Environment resolution={256} frames={1}>
        {/* Sky dome overhead */}
        <Lightformer form="rect" intensity={1.1} color="#eef5ff" scale={[60, 60, 1]} position={[0, 32, 0]} rotation={[Math.PI / 2, 0, 0]} />
        {/* Warm sun side */}
        <Lightformer form="rect" intensity={2.3} color="#fff0d6" scale={[14, 28, 1]} position={[20, 15, 10]} rotation={[0, -Math.PI / 3, 0]} />
        {/* Cool sky fill, opposite */}
        <Lightformer form="rect" intensity={1.4} color="#dce9ff" scale={[16, 28, 1]} position={[-20, 14, -6]} rotation={[0, Math.PI / 2.4, 0]} />
        {/* Vertical "reflected city" streaks that read in the glass facade */}
        <Lightformer form="rect" intensity={1.0} color="#ffffff" scale={[1.4, 24, 1]} position={[11, 12, -16]} />
        <Lightformer form="rect" intensity={0.8} color="#cfe0f7" scale={[1.0, 20, 1]} position={[-8, 10, -17]} />
        <Lightformer form="rect" intensity={0.9} color="#ffffff" scale={[1.2, 22, 1]} position={[3, 11, -18]} />
        {/* FRONT sky + city — what the camera-facing glass faces actually mirror.
            Without these the front facade has nothing bright to reflect and reads
            matte. Placed behind/above the camera (+z, high). */}
        <Lightformer form="rect" intensity={1.7} color="#f4f9ff" scale={[44, 30, 1]} position={[0, 22, 34]} rotation={[0, Math.PI, 0]} />
        <Lightformer form="rect" intensity={1.3} color="#ffffff" scale={[1.6, 26, 1]} position={[-7, 11, 24]} rotation={[0, Math.PI, 0]} />
        <Lightformer form="rect" intensity={1.1} color="#dbe8fb" scale={[1.2, 22, 1]} position={[9, 12, 26]} rotation={[0, Math.PI, 0]} />
        {/* Ground bounce */}
        <Lightformer form="rect" intensity={0.5} color="#eef1f6" scale={[44, 44, 1]} position={[0, -3, 0]} rotation={[-Math.PI / 2, 0, 0]} />
      </Environment>

      {/* Blueprint plane — sits flat on the ground. Sized to frame the larger
          highrise footprint with parchment border around it. */}
      <mesh
        ref={blueprintRef}
        rotation-x={-Math.PI / 2}
        position={[0, 0.01, 0]}
        receiveShadow
      >
        <planeGeometry args={[14, 10]} />
        <meshBasicMaterial
          ref={blueprintMat}
          map={blueprintTex}
          transparent
          toneMapped={false}
        />
      </mesh>

      {/* Vertical holographic light beams */}
      {beamPositions.map((b, i) => (
        <mesh
          key={b.key}
          ref={(el) => { beamRefs.current[i] = el; }}
          position={[b.x, 0, b.z]}
        >
          <cylinderGeometry args={[0.04, 0.04, 1, 8, 1, true]} />
          <meshStandardMaterial
            color="#5C82FF"
            emissive="#2F5BFF"
            emissiveIntensity={2.5}
            transparent
            opacity={0}
            toneMapped={false}
            side={THREE.DoubleSide}
          />
        </mesh>
      ))}

      {/* Podium — the plaza block the slender shaft rises from */}
      <group ref={podiumRef} position={[0, 0, 0]}>
        <mesh position={[0, PODIUM_H / 2, 0]} castShadow receiveShadow>
          <boxGeometry args={[PODIUM_W, PODIUM_H, PODIUM_D]} />
          <meshPhysicalMaterial
            color="#c4d2e6" roughness={0.18} metalness={0.1} ior={1.5}
            clearcoat={1} clearcoatRoughness={0.05} envMapIntensity={1.3}
            transparent opacity={0.96}
          />
        </mesh>
        <mesh position={[0, PODIUM_H + 0.05, 0]} castShadow>
          <boxGeometry args={[PODIUM_W + 0.12, 0.1, PODIUM_D + 0.12]} />
          <meshStandardMaterial color="#eef3f8" roughness={0.6} metalness={0.04} />
        </mesh>
      </group>

      {/* Tower — one glass curtain-wall band + one concrete slab edge per floor.
          The group origin sits at the floor base so scroll-driven scale.y grows
          the plate upward. A straight, classical shaft (no offsets). */}
      {FLOORS.map((f, i) => {
        const glassH = FLOOR_H * GLASS_FRAC;
        const slabH = FLOOR_H - glassH;
        return (
          <group
            key={f.i}
            ref={(el) => { floorRefs.current[i] = el; }}
            position={[f.x, f.baseY, f.z]}
          >
            <mesh position={[0, glassH / 2, 0]} castShadow receiveShadow>
              <boxGeometry args={[f.w, glassH, f.d]} />
              <meshPhysicalMaterial
                color="#6e93c0"
                roughness={0.045}
                metalness={0.15}
                ior={1.5}
                reflectivity={0.9}
                clearcoat={1}
                clearcoatRoughness={0.03}
                envMapIntensity={2.6}
                transparent
                opacity={0.93}
              />
            </mesh>
            {/* Thin concrete floor-slab edge — faint floor lines, slightly proud */}
            <mesh position={[0, glassH + slabH / 2, 0]} castShadow receiveShadow>
              <boxGeometry args={[f.w + 0.05, slabH, f.d + 0.05]} />
              <meshStandardMaterial color="#cdd8e6" roughness={0.5} metalness={0.04} envMapIntensity={1.0} />
            </mesh>
          </group>
        );
      })}

      {/* Anish Kapoor mirror "bean" at the plaza — a nod to the real 56 Leonard */}
      <group ref={beanRef} position={[PODIUM_W / 2 + 1.5, 0.5, PODIUM_D / 2 + 0.7]}>
        <mesh scale={[1.5, 0.62, 1.05]} castShadow receiveShadow>
          <sphereGeometry args={[0.7, 48, 32]} />
          <meshStandardMaterial color="#e8edf3" metalness={1} roughness={0.03} envMapIntensity={2.2} />
        </mesh>
      </group>

      {/* Ground — concrete plane with a tileable street grid (no hard receiveShadow;
          ContactShadows below does the soft grounding instead) */}
      <mesh rotation-x={-Math.PI / 2} position={[0, 0, 0]}>
        <planeGeometry args={[200, 200]} />
        <meshStandardMaterial
          ref={groundMat}
          map={groundTex}
          color="#FFFFFF"
          roughness={0.92}
          metalness={0.02}
          transparent
          opacity={0}
        />
      </mesh>

      {/* Soft contact shadow grounding the tower + city in the plaza */}
      <ContactShadows
        position={[0, 0.04, 0]}
        scale={64}
        far={28}
        blur={2.6}
        opacity={0.42}
        color="#8a98b0"
        resolution={512}
        frames={Infinity}
      />

      {/* Surrounding city — detailed glass-facade buildings (floor lines +
          windows via the shared facade texture), muted grey/creme/taupe tints,
          rising + fading in (staggered) on scroll. */}
      {cityBuildings.map((b, i) => (
        <mesh
          key={i}
          ref={(el) => { cityRefs.current[i] = el; }}
          position={[b.x, b.h / 2, b.z]}
          castShadow
          receiveShadow
        >
          <boxGeometry args={[b.w, b.h, b.d]} />
          <meshStandardMaterial
            map={facadeTex}
            color={b.color}
            roughness={b.glassy ? 0.34 : 0.62}
            metalness={b.glassy ? 0.3 : 0.06}
            envMapIntensity={b.glassy ? 0.85 : 0.4}
            transparent
            opacity={0}
          />
          <Edges threshold={15} color="#9fb0c8" />
        </mesh>
      ))}

      {/* Street life — low-poly trees, little people, cars. Hidden until the
          city ground is in (toggled in useFrame). Adds the polished, lived-in
          axonometric-render vibe without going photoreal. */}
      <group ref={propsRef} visible={false}>
        {streetProps.trees.map((t, i) => (
          <group key={`t${i}`} position={[t.x, 0, t.z]} scale={t.s}>
            <mesh position={[0, 0.34, 0]} castShadow>
              <cylinderGeometry args={[0.05, 0.08, 0.68, 6]} />
              <meshStandardMaterial color="#8a6b4f" roughness={0.92} />
            </mesh>
            <mesh position={[0, 0.98, 0]} castShadow>
              <icosahedronGeometry args={[0.5, 0]} />
              <meshStandardMaterial color={t.tone} roughness={0.85} flatShading />
            </mesh>
            <mesh position={[0.16, 1.28, 0.05]} castShadow>
              <icosahedronGeometry args={[0.3, 0]} />
              <meshStandardMaterial color={t.tone} roughness={0.85} flatShading />
            </mesh>
          </group>
        ))}
        {streetProps.people.map((p, i) => (
          <group key={`p${i}`} position={[p.x, 0, p.z]} rotation={[0, p.rot, 0]}>
            <mesh position={[0, 0.16, 0]}>
              <capsuleGeometry args={[0.045, 0.17, 3, 6]} />
              <meshStandardMaterial color={p.tone} roughness={0.8} />
            </mesh>
            <mesh position={[0, 0.33, 0]}>
              <sphereGeometry args={[0.05, 8, 8]} />
              <meshStandardMaterial color="#d7c2ac" roughness={0.8} />
            </mesh>
          </group>
        ))}
        {streetProps.cars.map((c, i) => (
          <group key={`c${i}`} position={[c.x, 0.12, c.z]} rotation={[0, c.rot, 0]}>
            <mesh castShadow>
              <boxGeometry args={[0.52, 0.2, 0.98]} />
              <meshStandardMaterial color={c.color} roughness={0.35} metalness={0.35} envMapIntensity={1} />
            </mesh>
            <mesh position={[0, 0.16, -0.05]}>
              <boxGeometry args={[0.46, 0.16, 0.5]} />
              <meshStandardMaterial color={c.color} roughness={0.2} metalness={0.4} envMapIntensity={1.2} />
            </mesh>
          </group>
        ))}
      </group>
    </>
  );
}

// Tiny seeded PRNG so tree layout is stable across reloads.
function mulberry32(seed: number) {
  let a = seed >>> 0;
  return () => {
    a |= 0; a = (a + 0x6D2B79F5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// ────────────────── Public component ────────────────────────────

export default function BuildingScene({ progress }: { progress: MotionValue<number> }) {
  // R3F observes its parent via ResizeObserver. Inside a sticky container, the
  // observer occasionally locks onto a stale ~150px measurement at mount and
  // never recovers — a manual resize event after mount forces it to re-measure
  // against the actual viewport.
  useEffect(() => {
    const fire = () => window.dispatchEvent(new Event("resize"));
    const t1 = setTimeout(fire, 50);
    const t2 = setTimeout(fire, 250);
    const t3 = setTimeout(fire, 800);
    return () => { clearTimeout(t1); clearTimeout(t2); clearTimeout(t3); };
  }, []);

  return (
    <div style={{ position: "absolute", top: 0, left: 0, width: "100vw", height: "100vh" }}>
      <Canvas
        shadows
        dpr={[1, 2]}
        camera={{ position: [0, 13, 4], fov: 35, near: 0.1, far: 200 }}
        gl={{ antialias: true, alpha: false, powerPreference: "high-performance", preserveDrawingBuffer: true }}
      >
        <SceneContents progress={progress} />
      </Canvas>
    </div>
  );
}
