'use client'

import { useState, useCallback } from 'react'
import ScenarioPicker from './ScenarioPicker'
import ProcessingAnimation from './ProcessingAnimation'
import TriageReportView from './TriageReportView'
import { DEMO_SCENARIOS } from '@/data/demo-scenarios'
import type { DemoScenario } from '@/data/demo-scenarios'

type Stage = 'idle' | 'processing' | 'complete'

// macOS-style browser chrome wrapping the demo content
function BrowserChrome({ children }: { children: React.ReactNode }) {
  return (
    <div className="rounded-xl overflow-hidden shadow-2xl border border-slate-700/60">
      {/* Title bar */}
      <div className="bg-slate-800 px-4 py-2.5 flex items-center gap-3">
        {/* Traffic lights */}
        <div className="flex gap-1.5 flex-shrink-0">
          <div className="w-3 h-3 rounded-full bg-red-400/80" />
          <div className="w-3 h-3 rounded-full bg-yellow-400/80" />
          <div className="w-3 h-3 rounded-full bg-green-400/80" />
        </div>
        {/* Fake URL bar */}
        <div className="flex-1 bg-slate-700 rounded-md px-3 py-1 flex items-center justify-center gap-1.5">
          <svg className="w-3 h-3 text-slate-500 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" />
          </svg>
          <span className="text-xs text-slate-400 font-mono">app.planroom.ai/queue/triage</span>
        </div>
        {/* Spacer to balance the traffic lights */}
        <div className="w-16 flex-shrink-0" />
      </div>

      {/* Content area */}
      <div className="bg-slate-50 min-h-96">
        {children}
      </div>
    </div>
  )
}

export default function DemoSection() {
  const [stage, setStage] = useState<Stage>('idle')
  const [selected, setSelected] = useState<DemoScenario | null>(null)

  const handleSelect = (scenario: DemoScenario) => {
    setSelected(scenario)
    setStage('processing')
  }

  const handleProcessingComplete = useCallback(() => {
    setStage('complete')
  }, [])

  const handleReset = () => {
    setSelected(null)
    setStage('idle')
  }

  return (
    <BrowserChrome>
      {stage === 'idle' && (
        <ScenarioPicker scenarios={DEMO_SCENARIOS} onSelect={handleSelect} />
      )}
      {stage === 'processing' && selected && (
        <ProcessingAnimation scenario={selected} onComplete={handleProcessingComplete} />
      )}
      {stage === 'complete' && selected && (
        <TriageReportView scenario={selected} onReset={handleReset} />
      )}
    </BrowserChrome>
  )
}
