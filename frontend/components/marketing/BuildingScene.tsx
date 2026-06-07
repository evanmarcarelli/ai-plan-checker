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
// Each block is a stacked Box. World units are meters (informally).
type Block = {
  x: number; z: number;
  w: number; d: number; h: number;
  greenRoof?: boolean;
};
const BLOCKS: Block[] = [
  { x:  0,   z:  0,   w: 4,   d: 3,   h: 5.0 },                  // main tower
  { x: -3,   z:  0,   w: 2.5, d: 3,   h: 3.0, greenRoof: true }, // side wing
  { x:  2.5, z:  0.5, w: 2,   d: 2.5, h: 2.2, greenRoof: true }, // annex
];

// ────────────────── Blueprint texture (procedural canvas) ────────────────────

function createBlueprintTexture(): THREE.CanvasTexture {
  const W = 1024, H = 768;
  const canvas = document.createElement("canvas");
  canvas.width = W; canvas.height = H;
  const ctx = canvas.getContext("2d")!;

  // Parchment fill
  ctx.fillStyle = "#F2EAD7";
  ctx.fillRect(0, 0, W, H);

  // Subtle warm vignette
  const grad = ctx.createRadialGradient(W / 2, H / 2, 200, W / 2, H / 2, 700);
  grad.addColorStop(0, "rgba(0,0,0,0)");
  grad.addColorStop(1, "rgba(120, 90, 40, 0.10)");
  ctx.fillStyle = grad;
  ctx.fillRect(0, 0, W, H);

  // Double border
  ctx.strokeStyle = "#1B3A8C";
  ctx.lineWidth = 2;
  ctx.strokeRect(40, 40, W - 80, H - 80);
  ctx.lineWidth = 1;
  ctx.strokeRect(52, 52, W - 104, H - 104);

  // Title block
  ctx.fillStyle = "#1B3A8C";
  ctx.font = 'bold 26px "Inter", system-ui, sans-serif';
  ctx.textAlign = "center";
  ctx.fillText("MULTI-USE MODERN BUILDING", W / 2, 96);
  ctx.font = '12px "DM Mono", monospace';
  ctx.fillStyle = "#2F5BFF";
  ctx.fillText("SHEET: PLAN-1   ·   SCALE 1:100   ·   UP2CODE PLAN REVIEW", W / 2, 116);

  // Subtle grid
  ctx.strokeStyle = "rgba(47, 91, 255, 0.10)";
  ctx.lineWidth = 0.5;
  for (let x = 64; x < W - 64; x += 32) {
    ctx.beginPath(); ctx.moveTo(x, 140); ctx.lineTo(x, H - 60); ctx.stroke();
  }
  for (let y = 144; y < H - 60; y += 32) {
    ctx.beginPath(); ctx.moveTo(64, y); ctx.lineTo(W - 64, y); ctx.stroke();
  }

  // World → canvas mapping. Plane is 8u × 6u, centered. Scale = 128 px/u.
  const SC = 128;
  const CX = W / 2, CY = H / 2;
  const wx = (x: number) => CX + x * SC;
  const wz = (z: number) => CY + z * SC;

  // Heavy block outlines
  ctx.strokeStyle = "#1B3A8C";
  ctx.lineWidth = 2.5;
  BLOCKS.forEach(b => {
    ctx.strokeRect(wx(b.x - b.w / 2), wz(b.z - b.d / 2), b.w * SC, b.d * SC);
  });

  // Interior grid lines (rooms, corridor)
  ctx.strokeStyle = "rgba(47, 91, 255, 0.55)";
  ctx.lineWidth = 1;
  ctx.beginPath();
  // Main tower partitions
  ctx.moveTo(wx(-2), wz(-1.5)); ctx.lineTo(wx(-2), wz(1.5));
  ctx.moveTo(wx( 0), wz(-1.5)); ctx.lineTo(wx( 0), wz(1.5));
  ctx.moveTo(wx( 2), wz(-1.5)); ctx.lineTo(wx( 2), wz(1.5));
  // Corridor running through wing+tower
  ctx.moveTo(wx(-4.25), wz(0)); ctx.lineTo(wx(2.0), wz(0));
  ctx.stroke();

  // Dimension line — top
  ctx.strokeStyle = "#1B3A8C";
  ctx.lineWidth = 1;
  ctx.font = '11px "DM Mono", monospace';
  ctx.fillStyle = "#1B3A8C";
  const dyTop = 200;
  ctx.beginPath();
  ctx.moveTo(wx(-4.25), dyTop); ctx.lineTo(wx(3.75), dyTop);
  [-4.25, -1.75, 2.0, 3.75].forEach(x => {
    ctx.moveTo(wx(x), dyTop - 5); ctx.lineTo(wx(x), dyTop + 5);
  });
  ctx.stroke();
  ctx.fillText('32\'-0"', wx(-3),    dyTop - 8);
  ctx.fillText('48\'-0"', wx( 0.125), dyTop - 8);
  ctx.fillText('22\'-6"', wx( 2.875), dyTop - 8);

  // Dimension line — left
  const dxLeft = 200;
  ctx.beginPath();
  ctx.moveTo(dxLeft, wz(-1.75)); ctx.lineTo(dxLeft, wz(1.75));
  [-1.75, 0, 1.75].forEach(z => {
    ctx.moveTo(dxLeft - 5, wz(z)); ctx.lineTo(dxLeft + 5, wz(z));
  });
  ctx.stroke();
  ctx.save();
  ctx.translate(dxLeft - 16, wz(0));
  ctx.rotate(-Math.PI / 2);
  ctx.textAlign = "center";
  ctx.fillText('36\'-0"', 0, 0);
  ctx.restore();

  // Room labels
  ctx.fillStyle = "rgba(27, 58, 140, 0.7)";
  ctx.font = '10px "DM Mono", monospace';
  ctx.textAlign = "center";
  ctx.fillText("OFFICE TOWER", wx(0),    wz(-0.7));
  ctx.fillText("LOBBY",        wx(0),    wz( 0.7));
  ctx.fillText("WING",         wx(-3),   wz( 0));
  ctx.fillText("ANNEX",        wx( 2.5), wz( 0.5));

  // North arrow (bottom right)
  ctx.save();
  ctx.translate(W - 110, H - 110);
  ctx.strokeStyle = "#1B3A8C";
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  ctx.moveTo(0, -22); ctx.lineTo(-9, 9); ctx.lineTo(0, 3); ctx.lineTo(9, 9);
  ctx.closePath();
  ctx.stroke();
  ctx.fillStyle = "#1B3A8C";
  ctx.font = 'bold 11px "DM Mono", monospace';
  ctx.textAlign = "center";
  ctx.fillText("N", 0, -28);
  ctx.restore();

  // Footer stamp
  ctx.fillStyle = "rgba(27, 58, 140, 0.6)";
  ctx.font = '10px "DM Mono", monospace';
  ctx.textAlign = "left";
  ctx.fillText("DRAWN: UP2CODE AI   ·   REV 01   ·   2026-06-06", 70, H - 64);

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
  const blueprintMat = useRef<THREE.MeshStandardMaterial>(null);

  // ─── Beams (one per corner per block) ───
  const beamPositions = useMemo(() => {
    const out: { x: number; z: number; h: number; key: string }[] = [];
    BLOCKS.forEach((b, i) => {
      const hx = b.w / 2, hz = b.d / 2;
      [[-1,-1],[1,-1],[1,1],[-1,1]].forEach(([sx,sz], j) => {
        out.push({ x: b.x + sx * hx, z: b.z + sz * hz, h: b.h, key: `${i}-${j}` });
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
  // Start: bright white. End: soft sky-blue mist to match website palette.
  const fog = useMemo(() => new THREE.Fog("#E8EEF5", 28, 55), []);
  useEffect(() => {
    scene.fog = fog;
    scene.background = new THREE.Color("#FFFFFF"); // start white, matches website
    return () => { scene.fog = null; };
  }, [scene, fog]);

  // Pre-built color buffers to avoid GC every frame
  const bgColor = useRef(new THREE.Color());
  const fogColor = useRef(new THREE.Color());

  useFrame(() => {
    const p = progress.get();

    // ─── Camera path: high-angle drafting view → 3/4 view ───
    // Start at (0, 13, 4) — ~17° tilt from straight down. Reads as top-down
    // but has a well-defined up-vector (no gimbal lock). End at (9, 6, 11)
    // for the architectural 3/4 view of the finished building.
    const camT = smoothstep(0.05, 0.55, p);
    camera.position.x = lerp(0,  9,  camT);
    camera.position.y = lerp(13, 6,  camT);
    camera.position.z = lerp(4,  11, camT);
    camera.lookAt(0, lerp(0, 2.0, camT), 0);

    // ─── Background + fog crossfade (white → sky-blue mist) ───
    const sceneT = smoothstep(0.55, 0.85, p);
    const WHITE = new THREE.Color("#FFFFFF");
    const SKYBLUE = new THREE.Color("#E8EEF5");
    bgColor.current.copy(WHITE).lerp(SKYBLUE, sceneT);
    if (scene.background instanceof THREE.Color) scene.background.copy(bgColor.current);
    fogColor.current.copy(WHITE).lerp(SKYBLUE, sceneT);
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
    const buildT = smoothstep(0.35, 0.68, p);
    const solidT = smoothstep(0.68, 0.92, p);
    blockRefs.current.forEach((m, i) => {
      if (!m) return;
      const h = BLOCKS[i].h;
      const sy = Math.max(0.0001, buildT);
      m.scale.y = sy;
      m.position.y = (h * sy) / 2;
      const mat = blockMats.current[i];
      if (mat) {
        // Glass: high transmission early, drops to a more solid facade later
        mat.transmission = lerp(0.85, 0.25, solidT);
        mat.opacity = lerp(0.35, 0.95, solidT);
        mat.roughness = lerp(0.08, 0.22, solidT);
      }
    });
    roofRefs.current.forEach((m, i) => {
      if (!m) return;
      const b = BLOCKS[i];
      if (!b.greenRoof) return;
      const sy = Math.max(0.0001, buildT);
      m.position.y = b.h * sy + 0.06;
      const mat = m.material as THREE.MeshStandardMaterial;
      mat.opacity = solidT;
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

      {/* Blueprint plane — sits flat on the ground */}
      <mesh
        ref={blueprintRef}
        rotation-x={-Math.PI / 2}
        position={[0, 0.01, 0]}
        receiveShadow
      >
        <planeGeometry args={[8, 6]} />
        <meshStandardMaterial
          ref={blueprintMat}
          map={blueprintTex}
          roughness={0.95}
          metalness={0}
          transparent
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
            color="#7DB0FF"
            emissive="#3B82F6"
            emissiveIntensity={2.5}
            transparent
            opacity={0}
            toneMapped={false}
            side={THREE.DoubleSide}
          />
        </mesh>
      ))}

      {/* Building blocks */}
      {BLOCKS.map((b, i) => (
        <group key={i}>
          <mesh
            ref={(el) => { blockRefs.current[i] = el; }}
            position={[b.x, b.h / 2, b.z]}
            castShadow
            receiveShadow
          >
            <boxGeometry args={[b.w, b.h, b.d]} />
            <meshPhysicalMaterial
              ref={(el) => { blockMats.current[i] = el; }}
              color="#E8F1FF"
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
              position={[b.x, b.h + 0.06, b.z]}
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
      ))}

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
