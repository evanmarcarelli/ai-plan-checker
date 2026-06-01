'use client'

import { useEffect, useState } from 'react'
import type { DemoScenario } from '@/data/demo-scenarios'

interface Props {
  scenario: DemoScenario
  onComplete: () => void
}

// Timing: each index maps to the delay at which that stage gets its checkmark
const STAGE_DELAYS_MS = [0, 650, 1200, 1800, 2400, 3100, 3800]
const COMPLETE_DELAY_MS = 4400

function buildStages(s: DemoScenario): string[] {
  const n = s.processingNotes
  return [
    `Surveying jurisdiction: ${n.jurisdiction}`,
    'Resolving property overlays (WUI, FEMA flood, coastal zone)…',
    'Extracting building scope from plan set…',
    `Evaluating ${n.ruleCount} code rules…`,
    'Searching pre-indexed corpus (CBC, LAMC, WSBC)…',
    `Researching ${n.citationCount} failing citation${n.citationCount !== 1 ? 's' : ''}…`,
    'Generating completeness report…',
  ]
}

export default function ProcessingAnimation({ scenario, onComplete }: Props) {
  const [completed, setCompleted] = useState<Set<number>>(new Set())
  const stages = buildStages(scenario)

  useEffect(() => {
    const timers: ReturnType<typeof setTimeout>[] = []

    STAGE_DELAYS_MS.forEach((delay, i) => {
      timers.push(
        setTimeout(() => setCompleted(prev => new Set([...prev, i])), delay),
      )
    })
    timers.push(setTimeout(onComplete, COMPLETE_DELAY_MS))

    return () => timers.forEach(clearTimeout)
  }, [onComplete])

  // Index of the stage currently in-flight (first one not yet completed)
  const activeIdx = stages.findIndex((_, i) => !completed.has(i))

  return (
    <div className="p-10 flex flex-col items-center justify-center min-h-64">
      <div className="w-full max-w-sm space-y-3.5">
        {stages.map((stage, i) => {
          const done = completed.has(i)
          const active = activeIdx === i

          return (
            <div
              key={i}
              className={`flex items-center gap-3 transition-opacity duration-300 ${
                done || active ? 'opacity-100' : 'opacity-0'
              }`}
            >
              {/* Icon: checkmark when done, spinner when active */}
              {done ? (
                <div className="w-5 h-5 rounded-full bg-emerald-100 flex items-center justify-center flex-shrink-0">
                  <svg className="w-3 h-3 text-emerald-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                  </svg>
                </div>
              ) : (
                <div className="w-5 h-5 rounded-full border-2 border-blue-200 border-t-blue-500 animate-spin flex-shrink-0" />
              )}

              <span className={`text-sm ${done ? 'text-slate-700' : 'text-slate-400'}`}>
                {stage}
              </span>
            </div>
          )
        })}
      </div>
    </div>
  )
}
