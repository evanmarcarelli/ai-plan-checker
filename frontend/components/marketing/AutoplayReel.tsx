"use client";

import {
  motion,
  AnimatePresence,
  useReducedMotion,
} from "framer-motion";
import { useEffect, useRef, useState } from "react";

const EASE = [0.23, 1, 0.32, 1] as const;
const SCENE_MS = 5200;

const CHAPTERS = [
  { id: "pain",    title: "The submittal loop"   },
  { id: "intro",   title: "Meet Architechtura"         },
  { id: "upload",  title: "Drop the plan set"    },
  { id: "process", title: "Multi-agent review"   },
  { id: "findings",title: "Findings, cited"      },
  { id: "teams",   title: "From AEC teams"       },
] as const;

/* ─── Root ──────────────────────────────────────────────────────────── */
export default function AutoplayReel() {
  const reduce = useReducedMotion();
  const [idx, setIdx] = useState(0);
  const [paused, setPaused] = useState(false);
  // The reel auto-advances only after it has scrolled into view. Before that,
  // it stays parked on chapter 0 so a visitor arriving at the top of the page
  // doesn't burn through the entire narrative before they ever see it.
  const sectionRef = useRef<HTMLElement>(null);
  const [inView, setInView] = useState(false);

  useEffect(() => {
    const el = sectionRef.current;
    if (!el) return;
    const obs = new IntersectionObserver(
      (entries) => {
        for (const e of entries) {
          if (e.isIntersecting) {
            setInView(true);
            obs.disconnect(); // one-shot — once started, keep cycling
            return;
          }
        }
      },
      // Fire when ~25% of the reel is on screen — enough to read the heading.
      { threshold: 0.25 },
    );
    obs.observe(el);
    return () => obs.disconnect();
  }, []);

  useEffect(() => {
    if (reduce || paused || !inView) return;
    const t = setTimeout(() => setIdx(i => (i + 1) % CHAPTERS.length), SCENE_MS);
    return () => clearTimeout(t);
  }, [idx, paused, reduce, inView]);

  return (
    <section
      ref={sectionRef}
      className="relative px-6 py-20 lg:py-28 overflow-hidden"
      style={{ background: "var(--bg)" }}
    >
      {/* Soft gold atmospheric backdrop */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0"
        style={{
          background:
            "radial-gradient(900px 500px at 75% 30%, rgba(184,148,31,0.07), transparent 70%)",
        }}
      />

      <div className="relative max-w-7xl mx-auto grid lg:grid-cols-[5fr_7fr] gap-12 lg:gap-16 items-center">
        {/* ── Copy column ───────────────────────────────────────────── */}
        <div>
          <div
            className="text-[11px] tracking-[0.24em] font-semibold uppercase mb-5"
            style={{ color: "var(--accent)" }}
          >
            The platform
          </div>
          <h2
            className="text-[40px] md:text-[52px] font-bold tracking-tight leading-[1.05] mb-5"
            style={{ fontFamily: "var(--font-display)", color: "var(--text-primary)" }}
          >
            See Architechtura in motion.
          </h2>
          <p
            className="text-[17px] leading-relaxed max-w-md mb-10"
            style={{ color: "var(--text-secondary)" }}
          >
            Drop in a plan set, watch an army of specialist agents resolve your
            jurisdiction, audit every code chapter, and return a structured
            triage report. All in 90 seconds.
          </p>

          {/* Chapter list */}
          <ol className="space-y-1">
            {CHAPTERS.map((ch, i) => {
              const active = i === idx;
              return (
                <li key={ch.id}>
                  <button
                    onClick={() => setIdx(i)}
                    className="group flex items-center gap-4 w-full text-left py-2"
                  >
                    <div
                      className="relative w-8 h-px shrink-0 overflow-hidden"
                      style={{ background: "var(--border-bright)" }}
                    >
                      {active && inView && !reduce && !paused && (
                        <motion.div
                          key={`prog-${i}-${idx}`}
                          initial={{ scaleX: 0 }}
                          animate={{ scaleX: 1 }}
                          transition={{ duration: SCENE_MS / 1000, ease: "linear" }}
                          className="absolute inset-0 origin-left"
                          style={{ background: "var(--accent-bright)" }}
                        />
                      )}
                      {active && (reduce || paused || !inView) && (
                        <div
                          className="absolute inset-0"
                          style={{ background: "var(--accent-bright)" }}
                        />
                      )}
                    </div>
                    <span
                      className="text-[11px] tabular-nums shrink-0"
                      style={{
                        fontFamily: "var(--font-mono)",
                        color: "var(--text-muted)",
                      }}
                    >
                      {String(i + 1).padStart(2, "0")}
                    </span>
                    <span
                      className={`text-[14px] transition-colors duration-200 ${
                        active ? "font-semibold" : ""
                      }`}
                      style={{
                        color: active ? "var(--text-primary)" : "var(--text-secondary)",
                      }}
                    >
                      {ch.title}
                    </span>
                  </button>
                </li>
              );
            })}
          </ol>

          {!reduce && (
            <button
              onClick={() => setPaused(p => !p)}
              className="mt-8 text-[11px] tracking-[0.18em] font-semibold uppercase transition-colors duration-150"
              style={{ color: paused ? "var(--accent)" : "var(--text-muted)" }}
            >
              {paused ? "▷ Resume" : "∥ Pause"}
            </button>
          )}
        </div>

        {/* ── Reel stage ────────────────────────────────────────────── */}
        <div
          className="relative aspect-[16/10] rounded-2xl overflow-hidden"
          style={{
            background: "var(--bg-card)",
            border: "1px solid var(--border)",
            boxShadow:
              "0 30px 80px -20px rgba(11,14,20,0.16), 0 0 40px -10px rgba(184,148,31,0.10)",
          }}
          onMouseEnter={() => setPaused(true)}
          onMouseLeave={() => setPaused(false)}
        >
          {/* Backdrop atmospherics */}
          <div
            aria-hidden
            className="pointer-events-none absolute inset-0"
            style={{
              background:
                "radial-gradient(700px 400px at 50% 30%, rgba(184,148,31,0.06), transparent 70%)",
            }}
          />
          <div
            aria-hidden
            className="pointer-events-none absolute inset-0 opacity-[0.45]"
            style={{
              backgroundImage:
                "linear-gradient(rgba(11,14,20,0.04) 1px, transparent 1px), linear-gradient(90deg, rgba(11,14,20,0.04) 1px, transparent 1px)",
              backgroundSize: "40px 40px",
              maskImage:
                "radial-gradient(700px 500px at 50% 50%, black 30%, transparent 80%)",
              WebkitMaskImage:
                "radial-gradient(700px 500px at 50% 50%, black 30%, transparent 80%)",
            }}
          />

          <AnimatePresence mode="wait">
            {idx === 0 && <ScenePain key="pain" />}
            {idx === 1 && <SceneIntro key="intro" />}
            {idx === 2 && <SceneUpload key="upload" />}
            {idx === 3 && <SceneProcess key="process" />}
            {idx === 4 && <SceneFindings key="findings" />}
            {idx === 5 && <SceneTeams key="teams" />}
          </AnimatePresence>
        </div>
      </div>
    </section>
  );
}

/* ─── Scene container ───────────────────────────────────────────────── */
function SceneFrame({ children }: { children: React.ReactNode }) {
  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.4, ease: EASE }}
      className="absolute inset-0 flex items-center justify-center p-8 lg:p-10"
    >
      {children}
    </motion.div>
  );
}

/* ─── SCENE 1 — The submittal loop ──────────────────────────────────── */
function ScenePain() {
  const events = [
    { date: "Jan 12", label: "Submitted to LADBS",   tone: "neutral" as const, delay: 0.4 },
    { date: "Jan 27", label: "14 comments returned", tone: "bad"     as const, delay: 0.8 },
    { date: "Feb 09", label: "Resubmitted",          tone: "neutral" as const, delay: 1.2 },
    { date: "Feb 24", label: "9 comments returned",  tone: "bad"     as const, delay: 1.6 },
    { date: "Mar 11", label: "Resubmitted (rev 3)",  tone: "neutral" as const, delay: 2.0 },
  ];
  return (
    <SceneFrame>
      <div className="w-full max-w-md">
        <motion.div
          initial={{ opacity: 0, y: -6 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5, ease: EASE }}
          className="text-[10px] tracking-[0.24em] font-semibold uppercase mb-5 text-center"
          style={{ color: "var(--text-muted)" }}
        >
          A familiar timeline
        </motion.div>
        <div className="space-y-2.5" style={{ fontFamily: "var(--font-mono)" }}>
          {events.map(e => (
            <motion.div
              key={e.date}
              initial={{ opacity: 0, x: -10 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ delay: e.delay, duration: 0.45, ease: EASE }}
              className="flex items-center gap-4"
            >
              <div
                className="w-16 text-[12px]"
                style={{ color: "var(--text-muted)" }}
              >
                {e.date}
              </div>
              <div className="flex-1 flex items-center gap-3">
                <div
                  className="w-1.5 h-1.5 rounded-full"
                  style={{
                    background:
                      e.tone === "bad" ? "var(--non-compliant)" : "var(--text-muted)",
                  }}
                />
                <div
                  className="text-[13px]"
                  style={{
                    color:
                      e.tone === "bad" ? "var(--non-compliant)" : "var(--text-secondary)",
                  }}
                >
                  {e.label}
                </div>
              </div>
            </motion.div>
          ))}
        </div>
        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 2.8, duration: 0.6, ease: EASE }}
          className="mt-10 text-center"
        >
          <div
            className="text-[56px] md:text-[68px] font-bold tracking-tight leading-none"
            style={{ fontFamily: "var(--font-display)", color: "var(--text-primary)" }}
          >
            438 days.
          </div>
          <div className="mt-3 text-[13px]" style={{ color: "var(--text-secondary)" }}>
            Across 5 submittal attempts.
          </div>
        </motion.div>
      </div>
    </SceneFrame>
  );
}

/* ─── SCENE 2 — Meet Architechtura ────────────────────────────────────────── */
function SceneIntro() {
  return (
    <SceneFrame>
      <div className="text-center">
        <motion.div
          initial={{ opacity: 0, scale: 0.7 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ delay: 0.3, duration: 0.7, ease: EASE }}
          className="mx-auto w-16 h-16 rounded-2xl flex items-center justify-center mb-8 overflow-hidden"
          style={{
            background: "#fff",
            boxShadow: "0 0 60px -10px rgba(47,91,255,0.5)",
          }}
        >
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src="/logo.png"
            alt="Architechtura"
            className="w-11 h-11 object-contain"
          />
        </motion.div>
        <motion.h3
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.7, duration: 0.6, ease: EASE }}
          className="text-[56px] md:text-[80px] font-bold tracking-tight leading-none"
          style={{ fontFamily: "var(--font-display)", color: "var(--text-primary)" }}
        >
          Architechtura.
        </motion.h3>
        <motion.p
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 1.2, duration: 0.6, ease: EASE }}
          className="mt-5 text-[15px] max-w-sm mx-auto"
          style={{ color: "var(--text-secondary)" }}
        >
          A twelve-agent AI plan-check team for AEC.
        </motion.p>
      </div>
    </SceneFrame>
  );
}

/* ─── SCENE 3 — Drop the plan set ───────────────────────────────────── */
function SceneUpload() {
  return (
    <SceneFrame>
      <div className="w-full max-w-md">
        <motion.div
          initial={{ opacity: 0, y: -6 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5, ease: EASE }}
          className="text-center mb-7"
        >
          <div
            className="text-[10px] tracking-[0.24em] font-semibold uppercase mb-2"
            style={{ color: "var(--accent)" }}
          >
            Step 01
          </div>
          <div
            className="text-[26px] md:text-[32px] font-bold tracking-tight"
            style={{ fontFamily: "var(--font-display)", color: "var(--text-primary)" }}
          >
            Drop in any plan set.
          </div>
        </motion.div>

        <div
          className="relative h-56 rounded-2xl"
          style={{ border: "2px dashed var(--border-bright)" }}
        >
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ delay: 1.5, duration: 0.5, ease: EASE }}
            aria-hidden
            className="absolute inset-0 rounded-2xl pointer-events-none"
          >
            <div
              className="absolute inset-0 rounded-2xl"
              style={{ boxShadow: "inset 0 0 30px rgba(184,148,31,0.10)" }}
            />
            <div
              className="absolute -inset-2 rounded-2xl"
              style={{
                background:
                  "radial-gradient(closest-side, rgba(184,148,31,0.12), transparent)",
              }}
            />
          </motion.div>

          {/* File card flying in */}
          <motion.div
            initial={{ opacity: 0, y: -180, scale: 1.06 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            transition={{ delay: 0.5, duration: 1.0, ease: EASE }}
            className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2"
          >
            <div
              className="w-44 rounded-xl p-4"
              style={{
                background: "var(--bg-card)",
                border: "1px solid var(--border)",
                boxShadow: "0 18px 40px -12px rgba(11,14,20,0.18)",
              }}
            >
              <div className="flex items-center gap-2 mb-3">
                <div
                  className="w-8 h-10 rounded flex items-center justify-center"
                  style={{
                    background:
                      "linear-gradient(180deg, #FB7185 0%, #E11D48 100%)",
                  }}
                >
                  <span className="text-[9px] font-bold text-white tracking-wider">
                    PDF
                  </span>
                </div>
                <div
                  className="text-[11px] leading-tight"
                  style={{ fontFamily: "var(--font-mono)", color: "var(--text-primary)" }}
                >
                  Mixed_Use_4Story_LA.pdf
                </div>
              </div>
              <motion.div
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                transition={{ delay: 1.9, duration: 0.5, ease: EASE }}
                className="space-y-1.5"
              >
                <div
                  className="flex justify-between text-[10px]"
                  style={{ color: "var(--text-muted)" }}
                >
                  <span>47 sheets</span>
                  <span>184 MB</span>
                </div>
                <div
                  className="h-1 rounded-full overflow-hidden"
                  style={{ background: "var(--bg-elevated)" }}
                >
                  <motion.div
                    initial={{ scaleX: 0 }}
                    animate={{ scaleX: 1 }}
                    transition={{ delay: 2.2, duration: 2.2, ease: EASE }}
                    className="h-full origin-left"
                    style={{ background: "var(--accent-bright)" }}
                  />
                </div>
              </motion.div>
            </div>
          </motion.div>
        </div>

        <motion.p
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 4.0, duration: 0.5, ease: EASE }}
          className="text-center text-[12px] mt-5"
          style={{ fontFamily: "var(--font-mono)", color: "var(--text-muted)" }}
        >
          47 sheets parsed · text extracted from every drawing
        </motion.p>
      </div>
    </SceneFrame>
  );
}

/* ─── SCENE 4 — Multi-agent review ──────────────────────────────────── */
const AGENTS = [
  { name: "Ingest",        detail: "PDF parse · sheet split"      },
  { name: "Geometry",      detail: "Walls, doors, dimensions"     },
  { name: "Zoner",         detail: "Zonal chunking"               },
  { name: "Jurisdiction",  detail: "City, county, state"          },
  { name: "Code Edition",  detail: "Adopted version select"       },
  { name: "Overlays",      detail: "WUI · flood · coastal"        },
  { name: "IBC Matcher",   detail: "IBC section matching"         },
  { name: "Local Code",    detail: "LAMC, SMC, amendments"        },
  { name: "Accessibility", detail: "Title 24 · ADA"               },
  { name: "Energy",        detail: "Title 24 part 6"              },
  { name: "Critic",        detail: "Peer-reviews findings"        },
  { name: "Verifier",      detail: "Verifies each citation"       },
] as const;

function SceneProcess() {
  return (
    <SceneFrame>
      <div className="w-full max-w-2xl">
        <motion.div
          initial={{ opacity: 0, y: -6 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5, ease: EASE }}
          className="text-center mb-6"
        >
          <div
            className="text-[10px] tracking-[0.24em] font-semibold uppercase mb-2"
            style={{ color: "var(--accent)" }}
          >
            Step 02
          </div>
          <div
            className="text-[24px] md:text-[30px] font-bold tracking-tight"
            style={{ fontFamily: "var(--font-display)", color: "var(--text-primary)" }}
          >
            An army of agents goes to work.
          </div>
        </motion.div>
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
          {AGENTS.map((a, i) => {
            const enter = 0.35 + i * 0.18;
            const done = enter + 1.4;
            return (
              <motion.div
                key={a.name}
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: enter, duration: 0.4, ease: EASE }}
                className="rounded-lg p-2.5 flex items-center gap-2.5 min-w-0"
                style={{
                  background: "var(--bg-card)",
                  border: "1px solid var(--border)",
                  boxShadow: "0 1px 3px rgba(11,14,20,0.04)",
                }}
              >
                <div
                  className="w-7 h-7 rounded-md flex items-center justify-center text-[10px] font-semibold shrink-0 tabular-nums"
                  style={{
                    background: "var(--accent-glow)",
                    color: "var(--accent)",
                    fontFamily: "var(--font-mono)",
                  }}
                >
                  {String(i + 1).padStart(2, "0")}
                </div>
                <div className="flex-1 min-w-0">
                  <div
                    className="text-[11px] font-semibold truncate"
                    style={{ color: "var(--text-primary)" }}
                  >
                    {a.name}
                  </div>
                  <div
                    className="text-[9px] truncate"
                    style={{ color: "var(--text-muted)" }}
                  >
                    {a.detail}
                  </div>
                </div>
                <motion.div
                  initial={{ opacity: 0, scale: 0.6 }}
                  animate={{ opacity: 1, scale: 1 }}
                  transition={{ delay: done, duration: 0.3, ease: EASE }}
                  className="w-1.5 h-1.5 rounded-full shrink-0"
                  style={{
                    background: "var(--compliant)",
                    boxShadow: "0 0 6px rgba(21,128,61,0.5)",
                  }}
                />
              </motion.div>
            );
          })}
        </div>
      </div>
    </SceneFrame>
  );
}

/* ─── SCENE 5 — Findings on the plan ────────────────────────────────── */
function SceneFindings() {
  return (
    <SceneFrame>
      <div className="w-full max-w-3xl">
        <motion.div
          initial={{ opacity: 0, y: -6 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5, ease: EASE }}
          className="text-center mb-5"
        >
          <div
            className="text-[10px] tracking-[0.24em] font-semibold uppercase mb-2"
            style={{ color: "var(--accent)" }}
          >
            Step 03
          </div>
          <div
            className="text-[24px] md:text-[28px] font-bold tracking-tight"
            style={{ fontFamily: "var(--font-display)", color: "var(--text-primary)" }}
          >
            Every finding, cited on the sheet.
          </div>
        </motion.div>
        <div className="grid grid-cols-[1fr_220px] gap-4">
          {/* Plan sheet */}
          <motion.div
            initial={{ opacity: 0, scale: 0.97 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={{ delay: 0.4, duration: 0.6, ease: EASE }}
            className="rounded-xl p-4"
            style={{
              background: "var(--bg-card)",
              border: "1px solid var(--border)",
              boxShadow: "0 1px 3px rgba(11,14,20,0.04)",
            }}
          >
            <div className="flex items-center justify-between mb-2.5">
              <div>
                <div
                  className="text-[9px] tracking-[0.18em] font-semibold uppercase mb-0.5"
                  style={{ color: "var(--text-muted)" }}
                >
                  Sheet A-201
                </div>
                <div
                  className="text-[12px] font-medium"
                  style={{ color: "var(--text-primary)" }}
                >
                  Egress Plan · Level 02
                </div>
              </div>
            </div>
            <div
              className="aspect-[16/9] rounded-lg p-3 relative"
              style={{
                background: "var(--bg-elevated)",
                border: "1px solid var(--border)",
              }}
            >
              <svg
                viewBox="0 0 400 220"
                className="w-full h-full"
                preserveAspectRatio="xMidYMid meet"
              >
                <rect x="10" y="10" width="380" height="200" fill="none" stroke="#0B1220" strokeWidth="1.3" />
                <rect x="40" y="40" width="160" height="70" fill="none" stroke="#0B1220" strokeOpacity="0.5" strokeWidth="0.8" />
                <rect x="220" y="40" width="140" height="70" fill="none" stroke="#0B1220" strokeOpacity="0.5" strokeWidth="0.8" />
                <rect x="40" y="135" width="320" height="60" fill="none" stroke="#0B1220" strokeOpacity="0.5" strokeWidth="0.8" />
                <line x1="120" y1="40" x2="120" y2="110" stroke="#0B1220" strokeOpacity="0.35" strokeWidth="0.6" />
                <line x1="290" y1="40" x2="290" y2="110" stroke="#0B1220" strokeOpacity="0.35" strokeWidth="0.6" />
                <path d="M 60 165 L 25 165 L 31 159 M 25 165 L 31 171" stroke="#2F5BFF" strokeWidth="1.3" fill="none" />
                <path d="M 340 165 L 375 165 L 369 159 M 375 165 L 369 171" stroke="#2F5BFF" strokeWidth="1.3" fill="none" />
              </svg>
              <Pin xPct={16} yPct={34} number={1} tone="red"   delay={1.2} />
              <Pin xPct={72} yPct={34} number={2} tone="amber" delay={1.7} />
              <Pin xPct={50} yPct={75} number={3} tone="red"   delay={2.2} />
            </div>
          </motion.div>

          {/* Findings list */}
          <motion.div
            initial={{ opacity: 0, x: 12 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ delay: 3.0, duration: 0.6, ease: EASE }}
            className="rounded-xl p-4 space-y-3"
            style={{
              background: "var(--bg-card)",
              border: "1px solid var(--border)",
              boxShadow: "0 1px 3px rgba(11,14,20,0.04)",
            }}
          >
            <div
              className="text-[9px] tracking-[0.18em] font-semibold uppercase mb-1"
              style={{ color: "var(--text-muted)" }}
            >
              Findings
            </div>
            <FindingRow n={1} tone="red"   title="Egress width below minimum" cite="IBC 1005.3.2" />
            <FindingRow n={2} tone="amber" title="Door swing direction unclear" cite="IBC 1010.1.2" />
            <FindingRow n={3} tone="red"   title="Travel distance exceeds max" cite="IBC 1017.2" />
            <div
              className="pt-2 border-t text-[10px]"
              style={{
                borderColor: "var(--border)",
                fontFamily: "var(--font-mono)",
                color: "var(--text-muted)",
              }}
            >
              3 of 11 · 38 citations
            </div>
          </motion.div>
        </div>
      </div>
    </SceneFrame>
  );
}

function Pin({
  xPct,
  yPct,
  number,
  tone,
  delay,
}: {
  xPct: number;
  yPct: number;
  number: number;
  tone: "red" | "amber";
  delay: number;
}) {
  const color = tone === "red" ? "var(--non-compliant)" : "var(--needs-review)";
  const ringColor = tone === "red" ? "#B91C1C" : "#F59E0B";
  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.4 }}
      animate={{ opacity: 1, scale: 1 }}
      transition={{ delay, duration: 0.45, ease: EASE }}
      style={{ left: `${xPct}%`, top: `${yPct}%` }}
      className="absolute -translate-x-1/2 -translate-y-1/2"
    >
      <div className="relative">
        <motion.div
          initial={{ opacity: 0.5, scale: 1 }}
          animate={{ opacity: 0, scale: 2.4 }}
          transition={{
            delay: delay + 0.3,
            duration: 1.2,
            ease: "easeOut",
            repeat: Infinity,
            repeatDelay: 0.8,
          }}
          className="absolute inset-0 rounded-full"
          style={{ background: ringColor }}
        />
        <div
          className="relative w-6 h-6 rounded-full flex items-center justify-center text-white text-[11px] font-semibold"
          style={{
            background: color,
            boxShadow: "0 2px 8px rgba(0,0,0,0.15)",
          }}
        >
          {number}
        </div>
      </div>
    </motion.div>
  );
}

function FindingRow({
  n,
  tone,
  title,
  cite,
}: {
  n: number;
  tone: "red" | "amber";
  title: string;
  cite: string;
}) {
  const color = tone === "red" ? "var(--non-compliant)" : "var(--needs-review)";
  return (
    <div className="flex items-start gap-2.5">
      <div
        className="mt-0.5 w-5 h-5 rounded-full flex items-center justify-center text-white text-[10px] font-semibold shrink-0"
        style={{ background: color }}
      >
        {n}
      </div>
      <div className="min-w-0">
        <div
          className="text-[11px] font-medium leading-snug"
          style={{ color: "var(--text-primary)" }}
        >
          {title}
        </div>
        <div
          className="text-[10px] mt-0.5"
          style={{ fontFamily: "var(--font-mono)", color: "var(--text-muted)" }}
        >
          {cite}
        </div>
      </div>
    </div>
  );
}

/* ─── SCENE 6 — From AEC teams ──────────────────────────────────────── */
function SceneTeams() {
  return (
    <SceneFrame>
      <div className="w-full max-w-3xl">
        <motion.div
          initial={{ opacity: 0, y: -6 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5, ease: EASE }}
          className="text-center mb-7"
        >
          <div
            className="text-[10px] tracking-[0.24em] font-semibold uppercase mb-2"
            style={{ color: "var(--accent)" }}
          >
            Early access
          </div>
          <div
            className="text-[26px] md:text-[32px] font-bold tracking-tight"
            style={{ fontFamily: "var(--font-display)", color: "var(--text-primary)" }}
          >
            From AEC teams using Architechtura.
          </div>
        </motion.div>
        <div className="grid grid-cols-3 gap-3">
          {[0.4, 0.8, 1.2].map((delay, i) => (
            <motion.div
              key={i}
              initial={{ opacity: 0, y: 24 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay, duration: 0.6, ease: EASE }}
              className="rounded-xl p-4 min-h-[150px] flex flex-col"
              style={{
                background: "var(--bg-card)",
                border: "1px solid var(--border)",
                boxShadow: "0 1px 3px rgba(11,14,20,0.04)",
              }}
            >
              <div className="flex items-center gap-2.5 mb-3">
                <div
                  className="w-8 h-8 rounded-full"
                  style={{
                    background: "var(--bg-elevated)",
                    border: "1px solid var(--border)",
                  }}
                />
                <div className="space-y-1">
                  <div
                    className="h-2 w-16 rounded-full"
                    style={{ background: "var(--bg-elevated)" }}
                  />
                  <div
                    className="h-1.5 w-24 rounded-full"
                    style={{ background: "var(--bg-elevated)" }}
                  />
                </div>
              </div>
              <div
                className="text-[12px] italic leading-relaxed"
                style={{ color: "var(--text-muted)" }}
              >
                Quotes from beta users coming soon.
              </div>
            </motion.div>
          ))}
        </div>
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 2.0, duration: 0.5, ease: EASE }}
          className="text-center mt-6"
        >
          <a
            href="/signup?redirect=/dashboard"
            className="inline-flex items-center justify-center px-5 py-2.5 rounded-lg text-[13px] font-semibold transition-opacity duration-150 hover:opacity-90"
            style={{ background: "var(--btn-primary-bg)", color: "var(--btn-primary-text)" }}
          >
            Request early access
          </a>
        </motion.div>
      </div>
    </SceneFrame>
  );
}
