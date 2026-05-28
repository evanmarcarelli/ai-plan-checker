"use client";

import { Home, Building2, Flame, ArrowRight } from "lucide-react";
import type { DemoScenario } from "./scenarios";

interface Props {
  scenarios: DemoScenario[];
  onSelect: (s: DemoScenario) => void;
}

const ICONS: Record<string, React.ElementType> = {
  "altadena-sfr": Flame,
  "la-sfr-adu": Home,
  "sf-commercial-ti": Building2,
};

export default function ScenarioPicker({ scenarios, onSelect }: Props) {
  return (
    <div className="p-6">
      <p className="text-xs text-center mb-5" style={{ color: "var(--text-muted)" }}>
        Pick a submittal type to run through the AI triage engine
      </p>
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        {scenarios.map(s => {
          const Icon = ICONS[s.id] ?? Home;
          return (
            <button
              key={s.id}
              onClick={() => onSelect(s)}
              className="finding-card text-left p-4 rounded-xl group"
              style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}
            >
              <div className="flex items-start justify-between mb-3">
                <div
                  className="w-9 h-9 rounded-lg flex items-center justify-center"
                  style={{ background: "var(--accent-glow)" }}
                >
                  <Icon className="w-4 h-4" style={{ color: "var(--accent-bright)" }} />
                </div>
                <ArrowRight
                  className="w-4 h-4 transition-transform group-hover:translate-x-0.5"
                  style={{ color: "var(--text-muted)" }}
                />
              </div>
              <h3
                className="font-semibold text-sm mb-0.5"
                style={{ color: "var(--text-primary)", fontFamily: "var(--font-display)" }}
              >
                {s.label}
              </h3>
              <p className="text-xs" style={{ color: "var(--text-muted)" }}>
                {s.location}
              </p>
              <p className="text-xs mt-2 leading-snug" style={{ color: "var(--text-secondary)" }}>
                {s.description}
              </p>
              <div className="mt-3">
                <span
                  className="text-[10px] font-mono font-semibold px-2 py-0.5 rounded"
                  style={{
                    background: "var(--needs-review-bg)",
                    color: "var(--accent)",
                  }}
                >
                  {s.badgeText}
                </span>
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
}
