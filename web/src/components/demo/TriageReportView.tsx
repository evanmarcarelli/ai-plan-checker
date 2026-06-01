'use client'

import { useState, useEffect } from 'react'
import FindingCard from './FindingCard'
import type { DemoScenario } from '@/data/demo-scenarios'

interface Props {
  scenario: DemoScenario
  onReset: () => void
}

function scoreColor(s: number) {
  if (s >= 80) return { text: 'text-emerald-700', stroke: '#10b981' }
  if (s >= 60) return { text: 'text-amber-700', stroke: '#f59e0b' }
  return { text: 'text-red-700', stroke: '#ef4444' }
}

function gradeChip(g: string) {
  const map: Record<string, string> = {
    A: 'bg-emerald-100 text-emerald-800 border border-emerald-200',
    B: 'bg-blue-100 text-blue-800 border border-blue-200',
    C: 'bg-amber-100 text-amber-800 border border-amber-200',
    D: 'bg-orange-100 text-orange-800 border border-orange-200',
    F: 'bg-red-100 text-red-800 border border-red-200',
  }
  return map[g] ?? 'bg-slate-100 text-slate-600'
}

const CIRCUMFERENCE = 2 * Math.PI * 26 // r=26 → ~163.4

export default function TriageReportView({ scenario, onReset }: Props) {
  const [displayScore, setDisplayScore] = useState(0)
  const { report } = scenario
  const colors = scoreColor(report.completeness.score)
  const scope = report.scope

  // Animate score counter on mount
  useEffect(() => {
    const target = report.completeness.score
    let current = 0
    const steps = 40
    const interval = setInterval(() => {
      current += target / steps
      if (current >= target) {
        setDisplayScore(target)
        clearInterval(interval)
      } else {
        setDisplayScore(Math.round(current))
      }
    }, 1000 / steps)
    return () => clearInterval(interval)
  }, [report.completeness.score])

  // Sort findings: fail → warn → info → pass
  const ORDER: Record<string, number> = { fail: 0, warn: 1, info: 2, pass: 3 }
  const sorted = [...report.findings].sort((a, b) => (ORDER[a.status] ?? 4) - (ORDER[b.status] ?? 4))

  const scopeRows = [
    { label: 'Occupancy', value: scope.occupancies.join(' / ') },
    { label: 'Construction', value: scope.construction_type },
    { label: 'Total area', value: scope.building_area_sf ? `${scope.building_area_sf.toLocaleString()} SF` : null },
    { label: 'Stories', value: scope.stories_above },
    { label: 'Height', value: scope.height_ft ? `${scope.height_ft} ft` : null },
    { label: 'Sprinklered', value: scope.sprinklered === null ? null : scope.sprinklered ? 'Yes' : 'No' },
  ].filter(r => r.value !== null && r.value !== undefined)

  return (
    <div className="fade-in">
      {/* Sub-header */}
      <div className="flex items-start justify-between gap-4 px-4 py-3 border-b border-slate-200">
        <div>
          <h3 className="font-semibold text-slate-900 text-sm">{scenario.projectName}</h3>
          <p className="text-xs text-slate-500 mt-0.5">{scenario.address}</p>
          <div className="flex items-center gap-2 mt-1">
            <span className="font-mono text-xs text-blue-700 font-semibold">{scenario.jurisdiction}</span>
            <span className="text-slate-300">·</span>
            <span className="text-xs text-slate-500">{scenario.projectType}</span>
          </div>
        </div>
        <button
          onClick={onReset}
          className="text-xs text-blue-600 hover:text-blue-800 transition-colors flex-shrink-0 mt-0.5 whitespace-nowrap"
        >
          ← Try another
        </button>
      </div>

      <div className="p-4 grid grid-cols-1 lg:grid-cols-5 gap-4">
        {/* Left column: score + scope */}
        <div className="lg:col-span-2 space-y-3">
          {/* Score card */}
          <div className="bg-white border border-slate-200 rounded-lg p-4 shadow-sm">
            <div className="flex items-center gap-3">
              {/* Animated SVG ring */}
              <div className="relative w-16 h-16 flex-shrink-0">
                <svg viewBox="0 0 64 64" className="w-16 h-16 -rotate-90">
                  <circle cx="32" cy="32" r="26" fill="none" stroke="#e2e8f0" strokeWidth="6" />
                  <circle
                    cx="32" cy="32" r="26" fill="none"
                    stroke={colors.stroke}
                    strokeWidth="6"
                    strokeDasharray={`${(displayScore / 100) * CIRCUMFERENCE} ${CIRCUMFERENCE}`}
                    strokeLinecap="round"
                    style={{ transition: 'stroke-dasharray 25ms linear' }}
                  />
                </svg>
                <div className="absolute inset-0 flex items-center justify-center">
                  <span className={`text-lg font-bold ${colors.text}`}>{displayScore}</span>
                </div>
              </div>
              <div>
                <div className="flex items-center gap-2">
                  <span className="text-sm font-semibold text-slate-700">Completeness</span>
                  <span className={`text-xs font-bold px-2 py-0.5 rounded ${gradeChip(report.completeness.grade)}`}>
                    {report.completeness.grade}
                  </span>
                </div>
                <p className="text-xs text-slate-600 mt-0.5 leading-snug">{report.completeness.headline}</p>
              </div>
            </div>

            {/* Stats tally */}
            <div className="mt-3 pt-3 border-t border-slate-100 grid grid-cols-4 gap-1.5">
              {[
                { label: 'Fail', n: report.stats.fail, cls: 'text-red-700 bg-red-50' },
                { label: 'Warn', n: report.stats.warn, cls: 'text-amber-700 bg-amber-50' },
                { label: 'Pass', n: report.stats.pass, cls: 'text-emerald-700 bg-emerald-50' },
                { label: 'Info', n: report.stats.info, cls: 'text-blue-700 bg-blue-50' },
              ].map(({ label, n, cls }) => (
                <div key={label} className={`text-center py-1.5 rounded text-xs font-semibold ${cls}`}>
                  <div className="text-base font-bold leading-none mb-0.5">{n}</div>
                  {label}
                </div>
              ))}
            </div>
          </div>

          {/* Scope panel */}
          <div className="bg-white border border-slate-200 rounded-lg p-4 shadow-sm">
            <h4 className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-3">Building Scope</h4>
            <dl className="space-y-2">
              {scopeRows.map(({ label, value }) => (
                <div key={label} className="flex justify-between items-baseline gap-2">
                  <dt className="text-xs text-slate-500">{label}</dt>
                  <dd className="text-xs font-medium text-slate-800 text-right">{String(value)}</dd>
                </div>
              ))}
            </dl>

            {scope.wui_zone?.in_wui && (
              <div className="mt-3 pt-3 border-t border-slate-100">
                <div className="flex items-center gap-1.5">
                  <span className="w-2 h-2 rounded-full bg-red-400 flex-shrink-0" />
                  <span className="text-xs font-semibold text-red-700">
                    WUI: {scope.wui_zone.haz_class} FHSZ ({scope.wui_zone.sra_type})
                  </span>
                </div>
                <p className="text-xs text-slate-500 mt-0.5 ml-3.5">CBC Chapter 7A applies</p>
              </div>
            )}

            {scope.ambiguities.length > 0 && (
              <div className="mt-3 pt-3 border-t border-slate-100 space-y-1.5">
                <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide">Reviewer Questions</p>
                {scope.ambiguities.slice(0, 2).map((a, i) => (
                  <p key={i} className="text-xs text-amber-700 flex gap-1.5 items-start">
                    <span className="flex-shrink-0">⚑</span>
                    {a}
                  </p>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Right column: findings */}
        <div className="lg:col-span-3 space-y-2">
          <h4 className="text-xs font-semibold text-slate-500 uppercase tracking-wide">
            Findings ({report.findings.length})
          </h4>
          {sorted.map((f, i) => (
            <FindingCard
              key={f.rule_id}
              finding={f}
              defaultOpen={i < 2 && (f.status === 'fail' || f.status === 'warn')}
            />
          ))}
        </div>
      </div>
    </div>
  )
}
