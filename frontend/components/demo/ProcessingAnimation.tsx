"use client";

import { useEffect, useState } from "react";
import { Check } from "lucide-react";
import type { DemoScenario } from "./scenarios";

interface Props {
  scenario: DemoScenario;
  onComplete: () => void;
}

const STAGE_DELAYS_MS = [0, 650, 1200, 1800, 2400, 3100, 3800];
const COMPLETE_DELAY_MS = 4400;

function buildStages(s: DemoScenario): string[] {
  const n = s.processingNotes;
  return [
    `Surveying jurisdiction: ${n.jurisdiction}`,
    "Resolving property overlays (CalFire FHSZ, FEMA flood, coastal zone)…",
    "Extracting building scope from plan set…",
    `Evaluating ${n.ruleCount} code rules against the design…`,
    "Searching pre-indexed corpus (CBC, CRC, T24, NEC, LAMC, SFBC)…",
    `Researching ${n.citationCount} citation${n.citationCount !== 1 ? "s" : ""}…`,
    "Generating completeness report…",
  ];
}

export default function ProcessingAnimation({ scenario, onComplete }: Props) {
  const [completed, setCompleted] = useState<Set<number>>(new Set());
  const stages = buildStages(scenario);

  useEffect(() => {
    const timers: ReturnType<typeof setTimeout>[] = [];
    STAGE_DELAYS_MS.forEach((delay, i) => {
      timers.push(
        setTimeout(() => setCompleted(prev => {
          const next = new Set(prev);
          next.add(i);
          return next;
        }), delay),
      );
    });
    timers.push(setTimeout(onComplete, COMPLETE_DELAY_MS));
    return () => timers.forEach(clearTimeout);
  }, [onComplete]);

  const activeIdx = stages.findIndex((_, i) => !completed.has(i));

  return (
    <div className="p-10 flex flex-col items-center justify-center min-h-72">
      <div className="w-full max-w-md space-y-3.5">
        {stages.map((stage, i) => {
          const done = completed.has(i);
          const active = activeIdx === i;
          return (
            <div
              key={i}
              className={`flex items-center gap-3 transition-opacity duration-300 ${
                done || active ? "opacity-100" : "opacity-0"
              }`}
            >
              {done ? (
                <div
                  className="w-5 h-5 rounded-full flex items-center justify-center flex-shrink-0"
                  style={{ background: "var(--compliant-bg)" }}
                >
                  <Check className="w-3 h-3" style={{ color: "var(--compliant)" }} strokeWidth={3} />
                </div>
              ) : (
                <div
                  className="w-5 h-5 rounded-full border-2 flex-shrink-0 animate-spin"
                  style={{
                    borderColor: "var(--border-bright)",
                    borderTopColor: "var(--accent-bright)",
                  }}
                />
              )}
              <span
                className="text-sm"
                style={{ color: done ? "var(--text-primary)" : "var(--text-muted)" }}
              >
                {stage}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
