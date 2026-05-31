"use client";

import { usePathname } from "next/navigation";
import { AnimatePresence, motion } from "framer-motion";
import { useEffect, useState } from "react";

/**
 * Fades + slides children when the route changes. Wraps every page in the
 * App Router so the home → login → dashboard hop feels continuous instead of
 * snapping. Respects `prefers-reduced-motion` automatically (Framer Motion
 * collapses to instant transitions when the user OS setting is on).
 *
 * mode="wait" ensures the old page fully animates out before the new one
 * mounts — avoids the brief stack of two pages mid-transition on slower
 * paint cycles. The 220ms duration is the Stripe/Linear default: long enough
 * to register as a transition, short enough not to feel laggy.
 */
export default function PageTransition({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();

  // Skip the entrance animation on the very first paint so it doesn't fire
  // during initial SSR hydration. Without this guard the marketing home flashes
  // in on a hard refresh.
  const [hydrated, setHydrated] = useState(false);
  useEffect(() => {
    setHydrated(true);
  }, []);

  return (
    <AnimatePresence mode="wait" initial={false}>
      <motion.div
        key={pathname}
        initial={hydrated ? { opacity: 0, y: 8 } : false}
        animate={{ opacity: 1, y: 0 }}
        exit={{ opacity: 0, y: -8 }}
        transition={{ duration: 0.22, ease: [0.22, 1, 0.36, 1] }}
        className="min-h-full"
      >
        {children}
      </motion.div>
    </AnimatePresence>
  );
}
