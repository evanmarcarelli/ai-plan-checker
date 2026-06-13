"use client";

// Adaline-style scrolling hero. A tall outer container creates scroll runway;
// inside, a sticky viewport pins the 3D canvas + HTML overlays while the user
// scrolls. Scroll progress is a framer-motion MotionValue passed straight into
// the R3F scene — overlays react via useTransform without React re-renders.
//
// Sits ABOVE the existing <Hero/> on the marketing page.
import { useRef } from "react";
import dynamic from "next/dynamic";
import { motion, useScroll, useTransform } from "framer-motion";
import { ArrowUpRight } from "lucide-react";

// R3F touches `window` and `WebGLRenderingContext` — disable SSR.
const BuildingScene = dynamic(() => import("./BuildingScene"), {
  ssr: false,
  loading: () => <div style={{ position: "absolute", inset: 0, background: "#FFFFFF" }} />,
});

const TRUSTED_BY = ["SKANSKA", "AECOM", "PROCORE", "AUTODESK", "GENSLER", "JACOBS"];

export default function ScrollBuildingHero() {
  const containerRef = useRef<HTMLDivElement>(null);

  // Progress is 0 at top of container, 1 when its bottom hits viewport bottom.
  const { scrollYProgress } = useScroll({
    target: containerRef,
    offset: ["start start", "end end"],
  });

  // Overlay opacity curves — keep them in sync with BuildingScene's phase ranges.
  // The tagline stays anchored above the scene the entire scroll — it's the
  // narrative spine — so no time-based fade. Only the small wordmark and the
  // trusted-by row fade in/out by phase.
  const wordmarkOpacity = useTransform(scrollYProgress, [0.00, 0.12, 0.21], [1, 1, 0]);
  // Trusted-by rises in at the "final form" hold, then clears as the fly-in
  // begins so it isn't left floating while the camera dives into the building.
  const trustedOpacity  = useTransform(scrollYProgress, [0.55, 0.64, 0.69, 0.75], [0, 1, 1, 0]);
  const trustedY        = useTransform(scrollYProgress, [0.55, 0.64],             [12, 0]);
  // Bright-interior bloom: a quick veil to the page colour as the camera pushes
  // through the doors, handing straight off to the <Hero/> section below.
  const bloomOpacity    = useTransform(scrollYProgress, [0.92, 1.0],              [0, 1]);

  // Tagline vertical position: starts higher (above the plan set in the
  // lower half of the frame), then eases down once the plan fades and the
  // building rises so the line sits closer to the city skyline.
  const taglineTop     = useTransform(scrollYProgress, [0.0, 0.30, 0.673], ["22vh", "32vh", "32vh"]);
  // Tagline holds through the intro / final form, then fades as the dive begins.
  const taglineOpacity = useTransform(scrollYProgress, [0.67, 0.75], [1, 0]);

  return (
    <section
      ref={containerRef}
      // 520vh of scroll runway: the first ~350vh plays the blueprint→city
      // extrusion, the final ~170vh flies the camera through the front doors
      // into a bright lobby that hands off to the section below.
      className="relative w-full"
      style={{ height: "520vh", background: "#FFFFFF" }}
      aria-label="Architechtura: from blueprint to building"
    >
      <div className="sticky top-0 h-screen w-full overflow-hidden">
        {/* 3D scene fills the viewport */}
        <BuildingScene progress={scrollYProgress} />

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
          style={{ top: taglineTop, opacity: taglineOpacity }}
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

        {/* Bright-interior bloom — final veil that carries the eye out of the
            3D scene and into the page as the camera passes through the doors. */}
        <motion.div
          style={{ opacity: bloomOpacity, background: "var(--bg)" }}
          className="pointer-events-none absolute inset-0 z-10"
        />
      </div>
    </section>
  );
}
