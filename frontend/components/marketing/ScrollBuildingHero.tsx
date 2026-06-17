"use client";

// Adaline-style scrolling hero. A tall outer container creates scroll runway;
// inside, a sticky viewport pins the 3D canvas + HTML overlays while the user
// scrolls. Scroll progress is a framer-motion MotionValue passed straight into
// the R3F scene — overlays react via useTransform without React re-renders.
//
// Sits ABOVE the existing <Hero/> on the marketing page.
import { Component, useRef, type ReactNode } from "react";
import dynamic from "next/dynamic";
import { motion, useScroll, useTransform, useSpring } from "framer-motion";
import { ArrowUpRight } from "lucide-react";

// R3F touches `window` and `WebGLRenderingContext` — disable SSR.
const BuildingScene = dynamic(() => import("./BuildingScene"), {
  ssr: false,
  loading: () => <div style={{ position: "absolute", inset: 0, background: "#FFFFFF" }} />,
});

// A WebGL context can fail to initialize (GPU limits, a blocked/exhausted
// context, or low-end devices). The 3D hero is purely decorative, so catch any
// failure and fall back to a plain white backdrop instead of letting the throw
// take down the entire marketing page. The HTML overlays render either way.
class SceneBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  render() {
    if (this.state.failed) {
      return <div style={{ position: "absolute", inset: 0, background: "#FFFFFF" }} />;
    }
    return this.props.children;
  }
}

const TRUSTED_BY = ["SKANSKA", "AECOM", "PROCORE", "AUTODESK", "GENSLER", "JACOBS"];

export default function ScrollBuildingHero() {
  const containerRef = useRef<HTMLDivElement>(null);

  // Progress is 0 at top of container, 1 when its bottom hits viewport bottom.
  const { scrollYProgress } = useScroll({
    target: containerRef,
    offset: ["start start", "end end"],
  });

  // Smooth the raw scroll value before anything consumes it. Wheel notches,
  // trackpad momentum, and low-frequency touch scroll arrive in coarse chunks;
  // feeding those straight into the scene makes the tower snap between steps.
  // An over-damped spring (damping ≫ critical, so no overshoot) glides between
  // states and settles fast enough to still read as scroll-linked, not floaty.
  // Both the 3D scene and the HTML overlays read from this single smoothed
  // source so they stay perfectly in sync.
  const smoothProgress = useSpring(scrollYProgress, {
    stiffness: 110,
    damping: 30,
    mass: 0.5,
    restDelta: 0.0008,
  });

  // Overlay opacity curves — keep them in sync with BuildingScene's phase ranges.
  // The tagline stays anchored above the scene the entire scroll — it's the
  // narrative spine — so no time-based fade. Only the small wordmark and the
  // trusted-by row fade in/out by phase.
  const wordmarkOpacity = useTransform(smoothProgress, [0.00, 0.18, 0.32], [1, 1, 0]);
  const trustedOpacity  = useTransform(smoothProgress, [0.86, 0.97],       [0, 1]);
  const trustedY        = useTransform(smoothProgress, [0.86, 0.97],       [12, 0]);

  // Tagline vertical position: starts higher (above the plan set in the
  // lower half of the frame), then eases down once the plan fades and the
  // building rises so the line sits closer to the city skyline.
  const taglineTop = useTransform(smoothProgress, [0.0, 0.45, 1.0], ["22vh", "32vh", "32vh"]);

  return (
    <section
      ref={containerRef}
      // 350vh of scroll runway — three viewport-heights to play through the
      // full extrusion sequence without feeling rushed or interminable.
      className="relative w-full"
      style={{ height: "350vh", background: "#FFFFFF" }}
      aria-label="Architechtura: from blueprint to building"
    >
      <div className="sticky top-0 h-screen w-full overflow-hidden">
        {/* 3D scene fills the viewport (gracefully degrades if WebGL fails) */}
        <SceneBoundary>
          <BuildingScene progress={smoothProgress} />
        </SceneBoundary>

        {/* Architechtura wordmark — the site's primary logo treatment. Sits above
            the tagline through the parchment phase, then fades as the scene
            transitions to the building extrude. Mirrors the Nav logo. */}
        <motion.div
          style={{ opacity: wordmarkOpacity, top: "calc(22vh - 56px)" }}
          className="pointer-events-none absolute left-0 right-0 flex justify-center"
        >
          <div className="flex items-center gap-1.5">
            <span
              className="text-[28px] sm:text-[32px] font-semibold tracking-[-0.025em]"
              style={{ color: "#0B1220", fontFamily: "var(--font-display)" }}
            >
              {/* Wordmark — "Architechtura" followed by the northeast arrow */}
              Architechtura
            </span>
            <ArrowUpRight
              className="w-4 h-4 sm:w-[18px] sm:h-[18px]"
              strokeWidth={2.5}
              style={{ color: "#0B1220" }}
            />
          </div>
        </motion.div>

        {/* Tagline — anchored below the wordmark logo. Sits in the upper
            third while the plan set occupies the lower half of the frame,
            then eases down as the building rises so the line lives closer
            to the skyline at the end of the scroll. */}
        <motion.div
          style={{ top: taglineTop }}
          className="pointer-events-none absolute left-0 right-0 px-6"
        >
          <div className="max-w-3xl mx-auto text-center">
            <h2
              className="text-[22px] sm:text-[30px] lg:text-[38px] font-light leading-[1.15] tracking-[-0.02em]"
              style={{ color: "#0B1220", fontFamily: "var(--font-display)" }}
            >
              The single platform for modern planning,
              <br className="hidden sm:block" /> construction, and code pre-checks,{" "}
              <span style={{ fontWeight: 600 }}>Architechtura</span>.
            </h2>
          </div>
        </motion.div>

        {/* Trusted by — anchored to bottom */}
        <motion.div
          style={{ opacity: trustedOpacity, y: trustedY }}
          className="pointer-events-none absolute bottom-12 left-0 right-0 px-6"
        >
          <div className="max-w-4xl mx-auto text-center">
            <div
              className="text-[10px] font-semibold tracking-[0.32em] mb-4"
              style={{ color: "rgba(11, 18, 32, 0.55)" }}
            >
              TRUSTED BY
            </div>
            <div className="flex flex-wrap items-center justify-center gap-x-10 gap-y-3">
              {TRUSTED_BY.map((name) => (
                <span
                  key={name}
                  className="text-[13px] font-semibold tracking-[0.18em]"
                  style={{ color: "rgba(11, 18, 32, 0.62)" }}
                >
                  {name}
                </span>
              ))}
            </div>
          </div>
        </motion.div>

        {/* Scroll cue — tiny chevron at first frame, fades with wordmark */}
        <motion.div
          style={{ opacity: wordmarkOpacity }}
          className="pointer-events-none absolute bottom-10 left-0 right-0 flex justify-center"
        >
          <div className="flex flex-col items-center gap-2">
            <span
              className="text-[10px] font-semibold tracking-[0.3em]"
              style={{ color: "rgba(11, 18, 32, 0.45)" }}
            >
              SCROLL
            </span>
            <motion.div
              animate={{ y: [0, 6, 0] }}
              transition={{ duration: 1.6, repeat: Infinity, ease: "easeInOut" }}
              className="w-px h-6"
              style={{ background: "rgba(11, 18, 32, 0.35)" }}
            />
          </div>
        </motion.div>
      </div>
    </section>
  );
}
