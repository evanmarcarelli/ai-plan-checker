'use client'

import { useState } from 'react'
import type { DemoFinding } from '@/data/demo-scenarios'

interface FindingCardProps {
  finding: DemoFinding
  defaultOpen?: boolean
}

function statusBadge(s: string): string {
  const map: Record<string, string> = {
    fail: 'bg-red-100 text-red-800 border border-red-200',
    warn: 'bg-amber-100 text-amber-800 border border-amber-200',
    warning: 'bg-amber-100 text-amber-800 border border-amber-200',
    info: 'bg-blue-100 text-blue-800 border border-blue-200',
    pass: 'bg-emerald-100 text-emerald-800 border border-emerald-200',
  }
  return map[s] ?? 'bg-slate-100 text-slate-600'
}

function statusLabel(s: string): string {
  const map: Record<string, string> = { fail: 'Fail', warn: 'Warn', warning: 'Warn', info: 'Info', pass: 'Pass' }
  return map[s] ?? s
}

function severityDot(severity: string): string {
  const map: Record<string, string> = {
    critical: 'bg-red-500',
    major: 'bg-orange-400',
    moderate: 'bg-amber-400',
    minor: 'bg-slate-300',
  }
  return map[severity] ?? 'bg-slate-300'
}

export default function FindingCard({ finding, defaultOpen = false }: FindingCardProps) {
  const [open, setOpen] = useState(defaultOpen)

  return (
    <div className="border border-slate-200 rounded-lg overflow-hidden bg-white">
      {/* Header — always visible */}
      <button
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-start gap-3 p-3 text-left hover:bg-slate-50 transition-colors"
      >
        <span className={`text-xs font-semibold px-2 py-0.5 rounded flex-shrink-0 mt-0.5 ${statusBadge(finding.status)}`}>
          {statusLabel(finding.status)}
        </span>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="font-mono text-xs text-blue-700 font-semibold">{finding.code_ref}</span>
            <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${severityDot(finding.severity)}`} title={finding.severity} />
            <span className="text-xs text-slate-400 capitalize">{finding.severity}</span>
          </div>
          <p className="text-sm text-slate-700 mt-0.5 leading-snug">{finding.summary}</p>
        </div>
        <svg
          className={`w-4 h-4 text-slate-400 flex-shrink-0 mt-1 transition-transform duration-200 ${open ? 'rotate-180' : ''}`}
          fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}
        >
          <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {/* Expanded content */}
      <div className={`overflow-hidden transition-all duration-200 ${open ? 'max-h-[500px]' : 'max-h-0'}`}>
        <div className="px-3 pb-3 border-t border-slate-100 pt-3 space-y-3">
          <p className="text-xs text-slate-600 leading-relaxed">{finding.description}</p>

          {finding.evidence.length > 0 && (
            <div>
              <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-1.5">Evidence</p>
              <ul className="space-y-1">
                {finding.evidence.map((e, i) => (
                  <li key={i} className="text-xs text-slate-600 flex gap-1.5 items-start">
                    <span className="text-slate-300 flex-shrink-0 mt-0.5">▸</span>
                    {e}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {finding.citation && (
            <div className="bg-blue-50 border border-blue-200 rounded-md p-2.5">
              <p className="text-xs font-semibold text-blue-700 mb-1.5">Verified Citation</p>
              <blockquote className="text-xs text-blue-900 italic leading-relaxed border-l-2 border-blue-300 pl-2">
                &ldquo;{finding.citation.text}&rdquo;
              </blockquote>
              <a
                href={finding.citation.source_url}
                target="_blank"
                rel="noopener noreferrer"
                className="mt-1.5 text-xs text-blue-600 hover:text-blue-800 transition-colors inline-block"
              >
                {finding.citation.source_title} ↗
              </a>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
