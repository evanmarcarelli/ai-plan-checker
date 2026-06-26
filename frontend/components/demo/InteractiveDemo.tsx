"use client";

import { useCallback, useState } from "react";
import ScenarioPicker from "./ScenarioPicker";
import ProcessingAnimation from "./ProcessingAnimation";
import TriageReportView from "./TriageReportView";
import { DEMO_SCENARIOS, type DemoScenario } from "./scenarios";

type Stage = "idle" | "processing" | "complete";

// macOS-style browser chrome wrapping the demo content.
function BrowserChrome({
  urlText,
  children,
}: {
  urlText: string;
  children: React.ReactNode;
}) {
  return (
    <div
      className="rounded-2xl overflow-hidden shadow-premium"
      style={{ border: "1px solid var(--border)", background: "var(--bg-card)" }}
    >
      {/* Title bar */}
      <div
        className="px-4 py-2.5 flex items-center gap-3"
        style={{
          background: "var(--bg-elevated)",
          borderBottom: "1px solid var(--border)",
        }}
      >
        <div className="flex gap-1.5 flex-shrink-0">
          <span className="w-3 h-3 rounded-full" style={{ background: "#FF5F57" }} />
          <span className="w-3 h-3 rounded-full" style={{ background: "#FEBC2E" }} />
          <span className="w-3 h-3 rounded-full" style={{ background: "#28C840" }} />
        </div>
        <div
          className="flex-1 text-center text-xs font-mono"
          style={{ color: "var(--text-muted)" }}
        >
          {urlText}
        </div>
        <div className="w-12 flex-shrink-0" />
      </div>

      <div style={{ background: "var(--bg)" }} className="min-h-[420px]">
        {children}
      </div>
    </div>
  );
}

export default function InteractiveDemo() {
  const [stage, setStage] = useState<Stage>("idle");
  const [selected, setSelected] = useState<DemoScenario | null>(null);

  const handleSelect = (scenario: DemoScenario) => {
    setSelected(scenario);
    setStage("processing");
  };

  const handleProcessingComplete = useCallback(() => {
    setStage("complete");
  }, []);

  const handleReset = () => {
    setSelected(null);
    setStage("idle");
  };

  const urlText =
    stage === "idle"
      ? "architechtura.ai/dashboard"
      : selected
      ? `architechtura.ai/dashboard · ${selected.label}`
      : "architechtura.ai/dashboard";

  return (
    <BrowserChrome urlText={urlText}>
      {stage === "idle" && (
        <ScenarioPicker scenarios={DEMO_SCENARIOS} onSelect={handleSelect} />
      )}
      {stage === "processing" && selected && (
        <ProcessingAnimation scenario={selected} onComplete={handleProcessingComplete} />
      )}
      {stage === "complete" && selected && (
        <TriageReportView scenario={selected} onReset={handleReset} />
      )}
    </BrowserChrome>
  );
}
