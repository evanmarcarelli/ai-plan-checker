/**
 * Architechtura brand mark — a geometric "A" (the structure) with an ascending
 * northeast arrow lifting off its apex (blueprint → building). The "A" strokes
 * use `currentColor`, so the mark inherits the surrounding text color and adapts
 * to light/dark themes automatically; the arrow stays brand-blue in both.
 *
 * Size it via `className` (e.g. "w-6 h-6") or the `size` prop. The matching
 * favicon/app-icon tile lives at app/icon.svg + app/icon.png.
 */
import type { CSSProperties } from "react";

export default function BrandMark({
  size = 24,
  className,
  style,
  arrowColor = "#2F5BFF",
  "aria-hidden": ariaHidden = true,
}: {
  size?: number;
  className?: string;
  style?: CSSProperties;
  arrowColor?: string;
  "aria-hidden"?: boolean;
}) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 48 48"
      fill="none"
      className={className}
      style={style}
      aria-hidden={ariaHidden}
      xmlns="http://www.w3.org/2000/svg"
    >
      <g stroke="currentColor" strokeWidth={5} strokeLinecap="round" strokeLinejoin="round">
        <path d="M9 39 L21 15 L33 39" />
        <path d="M14.5 28.5 L27.5 28.5" />
      </g>
      <g stroke={arrowColor} strokeWidth={5} strokeLinecap="round" strokeLinejoin="round">
        <path d="M28 20 L40 8" />
        <path d="M31 8 L40 8 L40 17" />
      </g>
    </svg>
  );
}
