"use client";

import { motion, useReducedMotion } from "framer-motion";
import type { CSSProperties, ReactNode } from "react";

interface RevealProps {
  children: ReactNode;
  /** Stagger offset (in seconds) when revealing sibling Reveals in a list.
   *  e.g. `<Reveal delay={i * 0.06}>` for a clean cascade. */
  delay?: number;
  /** How far below the final position to start. Subtle = 12px. */
  y?: number;
  className?: string;
  style?: CSSProperties;
}

/**
 * Wraps content in a fade + slight upward translate that fires once the
 * element enters the viewport. Used for marketing-page sections so the page
 * feels alive on first scroll without anything jumping later.
 *
 * `once: true` + `amount: 0.25` is the Vercel/Linear default: trigger when
 * a quarter of the section is visible, then never re-animate on scroll-back.
 * Respects `prefers-reduced-motion` — returns children unwrapped if on.
 */
export default function Reveal({ children, delay = 0, y = 12, className, style }: RevealProps) {
  const reduced = useReducedMotion();
  if (reduced) {
    return <div className={className} style={style}>{children}</div>;
  }
  return (
    <motion.div
      initial={{ opacity: 0, y }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, amount: 0.25 }}
      transition={{ duration: 0.5, delay, ease: [0.22, 1, 0.36, 1] }}
      className={className}
      style={style}
    >
      {children}
    </motion.div>
  );
}
