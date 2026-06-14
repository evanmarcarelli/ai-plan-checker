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
import { Edges } from "@react-three/drei";
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

// ────────────────── Building footprint (single source of truth) ───────────────
// A slender glass tower in the "56 Leonard / Jenga" style: smooth shaft segments
// punctuated by MULTIPLE clusters of stacked, cantilevered boxes that jut in
// alternating directions — subtle low, more dramatic toward the top. Each block
// is a Box; world units are meters.
type Block = {
  x: number; z: number;
  w: number; d: number; h: number;
  greenRoof?: boolean;
  // Optional vertical offset (in world units) — used to stack blocks above
  // the podium without re-baselining them to ground level.
  baseY?: number;
  // Tint override so the tower body and crown can read differently.
  color?: string;
};
const BLOCKS: Block[] = [
  // Base the tower rises from
  { x: 0, z: 0, w: 6,   d: 5,   h: 2,   color: "#DCE8FA" },
  // Lower smooth glass shaft
  { x: 0, z: 0, w: 4,   d: 3.6, h: 4,   baseY: 2,   color: "#E8F1FF" },

  // ── Jenga cluster A (lower, subtle offsets) ──
  { x:  0.7, z:  0.3, w: 4.0, d: 3.6, h: 1.3, baseY:  6.0, color: "#E1ECFB" },
  { x: -0.6, z: -0.4, w: 4.0, d: 3.8, h: 1.3, baseY:  7.3, color: "#DAE8FA" },
  { x:  0.5, z:  0.5, w: 3.8, d: 3.4, h: 1.4, baseY:  8.6, color: "#E8F1FF" },

  // Mid smooth shaft
  { x: 0, z: 0, w: 3.8, d: 3.4, h: 2.5, baseY: 10.0, color: "#E8F1FF" },

  // ── Jenga cluster B (mid, medium offsets) ──
  { x: -0.9, z:  0.5, w: 4.0, d: 3.6, h: 1.3, baseY: 12.5, color: "#E1ECFB" },
  { x:  1.0, z: -0.6, w: 4.0, d: 3.8, h: 1.3, baseY: 13.8, color: "#DAE8FA" },
  { x: -0.6, z:  0.7, w: 3.8, d: 3.6, h: 1.4, baseY: 15.1, color: "#C9D8EE" },

  // Short smooth setback
  { x: 0, z: 0, w: 3.4, d: 3.0, h: 1.0, baseY: 16.5, color: "#E8F1FF" },

  // ── Jenga crown (top, most dramatic offsets) ──
  { x:  1.2, z:  0.6, w: 3.8, d: 3.2, h: 1.2, baseY: 17.5, color: "#E1ECFB" },
  { x: -1.1, z: -0.7, w: 3.6, d: 3.4, h: 1.2, baseY: 18.7, color: "#DAE8FA" },
  { x:  1.2, z:  0.6, w: 3.2, d: 2.8, h: 1.1, baseY: 19.9, color: "#C9D8EE" }, // top cap — aligned over the 3rd-from-top block (x:1.2, z:0.6)
];

// ────────────────── Blueprint texture (procedural canvas) ────────────────────

// Returns only the ground-level (baseY undefined or 0) blocks — the ones that
// appear in plan view and originate beams from the ground footprint.
const GROUND_BLOCKS = BLOCKS.filter((b) => !b.baseY);

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

// ────────────────── Scene contents (inside Canvas) ────────────────────────────

function SceneContents({ progress }: { progress: MotionValue<number> }) {
  const { scene, camera } = useThree();

  // ─── Blueprint plane ───
  const blueprintTex = useMemo(() => createBlueprintTexture(), []);
  useEffect(() => () => blueprintTex.dispose(), [blueprintTex]);

  const blueprintRef = useRef<THREE.Mesh>(null);
  const blueprintMat = useRef<THREE.MeshBasicMaterial>(null);

  // ─── Beams (one per corner per ground-level block) ───
  // Beams shoot up from the plan footprint, so only the ground-baseline blocks
  // produce them — and each beam runs to the total stacked height at that
  // tower's footprint, not just to its own block's roof.
  const beamPositions = useMemo(() => {
    // Total stack height per (x, z) tower footprint
    const stackHeight = (b: Block) => {
      let top = (b.baseY ?? 0) + b.h;
      BLOCKS.forEach((other) => {
        if (other === b) return;
        // any block whose footprint overlaps significantly with `b`
        const overlap =
          Math.abs(other.x - b.x) < (b.w + other.w) / 2 - 0.1 &&
          Math.abs(other.z - b.z) < (b.d + other.d) / 2 - 0.1;
        if (overlap) top = Math.max(top, (other.baseY ?? 0) + other.h);
      });
      return top;
    };
    const out: { x: number; z: number; h: number; key: string }[] = [];
    GROUND_BLOCKS.forEach((b, i) => {
      const hx = b.w / 2, hz = b.d / 2;
      const fullH = stackHeight(b);
      [[-1,-1],[1,-1],[1,1],[-1,1]].forEach(([sx,sz], j) => {
        out.push({ x: b.x + sx * hx, z: b.z + sz * hz, h: fullH, key: `${i}-${j}` });
      });
    });
    return out;
  }, []);
  const beamRefs = useRef<(THREE.Mesh | null)[]>([]);

  // ─── Building blocks ───
  const blockRefs = useRef<(THREE.Mesh | null)[]>([]);
  const blockMats = useRef<(THREE.MeshPhysicalMaterial | null)[]>([]);
  const roofRefs = useRef<(THREE.Mesh | null)[]>([]);

  // ─── City context ───
  const groundMat = useRef<THREE.MeshStandardMaterial>(null);
  const cityRefs = useRef<(THREE.Mesh | null)[]>([]);

  // Tileable street-grid ground texture
  const groundTex = useMemo(() => createCityGroundTexture(), []);
  useEffect(() => () => groundTex.dispose(), [groundTex]);

  // ─── Scene fog/background (animated) ───
  // Pure white → faint warm-grey mist. Keeps the whole composition black & white.
  const fog = useMemo(() => new THREE.Fog("#F2F2F2", 28, 55), []);
  useEffect(() => {
    scene.fog = fog;
    scene.background = new THREE.Color("#FFFFFF");
    return () => { scene.fog = null; };
  }, [scene, fog]);

  // Pre-built color buffers to avoid GC every frame
  const bgColor = useRef(new THREE.Color());
  const fogColor = useRef(new THREE.Color());

  useFrame(() => {
    const p = progress.get();

    // ─── Camera path: high-angle drafting view → 3/4 view ───
    // Start pulled WAY back and looking at a point ahead of the plan so the
    // sheet sits in the LOWER half of the viewport — leaves the top half for
    // the tagline. End farther back / higher so the 22u tall highrise reads.
    const camT = smoothstep(0.05, 0.55, p);
    camera.position.x = lerp(0,  15, camT);
    camera.position.y = lerp(26, 12, camT);
    camera.position.z = lerp(6,  18, camT);
    // Looking at a point ahead of the plan (negative Z = toward the back of
    // the world) shifts the sheet visually downward in the frame.
    camera.lookAt(0, lerp(0, 8.0, camT), lerp(-3.5, 0, camT));

    // ─── Background + fog crossfade (pure white → soft warm-grey mist) ───
    const sceneT = smoothstep(0.55, 0.85, p);
    const WHITE = new THREE.Color("#FFFFFF");
    const GREY  = new THREE.Color("#F2F2F2");
    bgColor.current.copy(WHITE).lerp(GREY, sceneT);
    if (scene.background instanceof THREE.Color) scene.background.copy(bgColor.current);
    fogColor.current.copy(WHITE).lerp(GREY, sceneT);
    fog.color.copy(fogColor.current);
    fog.near = lerp(40, 22, sceneT);
    fog.far  = lerp(90, 58, sceneT);

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

    // ─── Building blocks: extrude + glass-to-solid ───
    // Stacked blocks rise in tiers — a block at baseY=N only starts extruding
    // once the blocks below have largely formed. This gives the highrise a
    // real bottom-up construction feel instead of every floor materializing
    // simultaneously.
    const solidT = smoothstep(0.68, 0.92, p);
    // Tier boundaries based on how high each block sits. Tallest stack is ~22u.
    const STACK_MAX = 22;
    blockRefs.current.forEach((m, i) => {
      if (!m) return;
      const b = BLOCKS[i];
      const baseY = b.baseY ?? 0;
      // Per-tier delay: ground blocks fade in first, crown last.
      const tierFrac = baseY / STACK_MAX;          // 0..1
      const start = 0.35 + tierFrac * 0.30;        // ground=0.35, crown≈0.65
      const tierT = smoothstep(start, start + 0.16, p);
      const sy = Math.max(0.0001, tierT);
      m.scale.y = sy;
      m.position.y = baseY + (b.h * sy) / 2;
      // Hide block entirely until its tier begins extruding — otherwise the
      // flattened glass slab reads as a stray white panel on the blueprint.
      m.visible = tierT > 0.001;
      const mat = blockMats.current[i];
      if (mat) {
        // Glass: high transmission early, drops to a more solid facade later.
        // Multiply by tierT so the block's opacity ramps with its extrusion.
        mat.transmission = lerp(0.85, 0.25, solidT);
        mat.opacity = lerp(0.35, 0.95, solidT) * tierT;
        mat.roughness = lerp(0.08, 0.22, solidT);
      }
    });
    roofRefs.current.forEach((m, i) => {
      if (!m) return;
      const b = BLOCKS[i];
      if (!b.greenRoof) return;
      const baseY = b.baseY ?? 0;
      const tierFrac = baseY / STACK_MAX;
      const start = 0.35 + tierFrac * 0.30;
      const tierT = smoothstep(start, start + 0.16, p);
      const sy = Math.max(0.0001, tierT);
      m.position.y = baseY + b.h * sy + 0.06;
      m.visible = tierT > 0.001;
      const mat = m.material as THREE.MeshStandardMaterial;
      mat.opacity = solidT * tierT;
      mat.transparent = true;
    });

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
  });

  // ─── Surrounding city buildings ───
  // Scatter on a jittered grid around the hero. Skip its footprint and the
  // camera→hero foreground sightline. Taller toward the back for a skyline.
  // Each building carries a `delay` so the city rises in staggered waves.
  const cityBuildings = useMemo(() => {
    const rand = mulberry32(7);
    const GLASS = ["#C9D8EE", "#BFD2EC", "#D3E0F2", "#AFC6E4"];
    const CONCRETE = ["#D9DDE3", "#CFD4DB", "#E2E5EA", "#C7CDD5"];
    const out: {
      x: number; z: number; w: number; d: number; h: number;
      color: string; glass: boolean; delay: number;
    }[] = [];
    for (let gx = -28; gx <= 28; gx += 6.5) {
      for (let gz = -34; gz <= 8; gz += 6.5) {
        const x = gx + (rand() - 0.5) * 3.2;
        const z = gz + (rand() - 0.5) * 3.2;
        // Keep the hero footprint clear (with margin)
        if (Math.abs(x) < 7.5 && z > -5 && z < 5) continue;
        // Keep the camera→hero foreground sightline clear
        if (z > 3 && Math.abs(x) < 10) continue;
        // Random gaps so it doesn't read as a perfect grid
        if (rand() < 0.22) continue;
        const w = 2.2 + rand() * 2.8;
        const d = 2.2 + rand() * 2.8;
        const depth = clamp01((8 - z) / 42);           // 0 near .. 1 far back
        const h = lerp(2.4, 9.5, depth) * (0.7 + rand() * 0.6);
        const glass = rand() > 0.45;
        const color = glass
          ? GLASS[Math.floor(rand() * GLASS.length)]
          : CONCRETE[Math.floor(rand() * CONCRETE.length)];
        out.push({ x, z, w, d, h, color, glass, delay: rand() });
      }
    }
    return out;
  }, []);

  return (
    <>
      {/* Lights — warm key, cool fill, soft ambient */}
      <ambientLight intensity={0.55} color="#FFF6E6" />
      <hemisphereLight color="#DCE6F2" groundColor="#AEB6C2" intensity={0.45} />
      <directionalLight
        position={[10, 16, 8]}
        intensity={1.4}
        color="#FFF1D6"
        castShadow
        shadow-mapSize={[1024, 1024]}
        shadow-camera-left={-20}
        shadow-camera-right={20}
        shadow-camera-top={20}
        shadow-camera-bottom={-20}
        shadow-bias={-0.0005}
      />

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

      {/* Building blocks — stacked tiers honor baseY for podium → tower → crown */}
      {BLOCKS.map((b, i) => {
        const baseY = b.baseY ?? 0;
        return (
          <group key={i}>
            <mesh
              ref={(el) => { blockRefs.current[i] = el; }}
              position={[b.x, baseY + b.h / 2, b.z]}
              castShadow
              receiveShadow
            >
              <boxGeometry args={[b.w, b.h, b.d]} />
              <meshPhysicalMaterial
                ref={(el) => { blockMats.current[i] = el; }}
                color={b.color ?? "#E8F1FF"}
                transmission={0.85}
                thickness={0.6}
                roughness={0.08}
                metalness={0.0}
                ior={1.45}
                transparent
                opacity={0}
                attenuationColor="#BFD4F2"
                attenuationDistance={4}
                clearcoat={1}
                clearcoatRoughness={0.06}
              />
              <Edges threshold={15} color="#2F5BFF" />
            </mesh>
            {b.greenRoof && (
              <mesh
                ref={(el) => { roofRefs.current[i] = el; }}
                position={[b.x, baseY + b.h + 0.06, b.z]}
                castShadow
              >
                <boxGeometry args={[b.w * 0.96, 0.12, b.d * 0.96]} />
                <meshStandardMaterial
                  color="#5E7C4F"
                  roughness={0.9}
                  metalness={0}
                  transparent
                  opacity={0}
                />
              </mesh>
            )}
          </group>
        );
      })}

      {/* Ground — concrete plane with a tileable street grid */}
      <mesh
        rotation-x={-Math.PI / 2}
        position={[0, 0, 0]}
        receiveShadow
      >
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

      {/* Surrounding city — buildings rise + fade in (staggered) on scroll */}
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
            color={b.color}
            roughness={b.glass ? 0.18 : 0.82}
            metalness={b.glass ? 0.45 : 0.05}
            transparent
            opacity={0}
          />
          <Edges threshold={15} color="#8FA6C8" />
        </mesh>
      ))}
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
