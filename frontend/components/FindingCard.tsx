'use client'

// =====================================================================
// FindingCard
//
// Two-pane card:
//   - Left: finding metadata (rule, severity, summary, citation)
//   - Right: PdfAnnotationViewer locked to the finding's page +
//     evidence_location.bbox (when both pdfUrl and bbox are available)
//
// Designed to render the backend Finding shape from
// supabase/functions/_shared/evaluate.ts. The queue page can adapt
// its TriageFinding rows to this shape; the demo flow has its own
// FindingCard (web/src/components/demo/FindingCard.tsx) and is
// intentionally NOT changed here.
// =====================================================================

import { useState } from 'react'
import PdfAnnotationViewer, { AnnotationRegion } from './PdfAnnotationViewer'

export interface EvidenceLocation {
  text: string
  page: number | null
  bbox: { x: number; y: number; w: number; h: number } | null
  sheet?: string | null
}

export interface FindingCitation {
  text: string
  source_url: string
  source_title: string
  source_domain?: string
  confidence: number
  notes?: string
}

export interface FindingForCard {
  rule_id: string
  code_ref: string
  description: string
  discipline?: string
  severity: string                                  // critical | major | moderate | minor
  status: 'pass' | 'fail' | 'warn' | 'info'
  summary: string
  evidence?: string[]
  confidence: number
  evidence_location?: EvidenceLocation | null
  citation_unverified?: boolean
  citation?: FindingCitation
}

interface Props {
  finding: FindingForCard
  pdfUrl?: string | null     // signed Supabase Storage URL for the planset
  defaultOpen?: boolean
}

// --------------- visual maps ----------------------------------------
const severityBadge: Record<string, string> = {
  critical: 'bg-red-100 text-red-800 border-red-200',
  major:    'bg-orange-100 text-orange-800 border-orange-200',
  moderate: 'bg-amber-100 text-amber-800 border-amber-200',
  minor:    'bg-slate-100 text-slate-600 border-slate-200',
}

const statusBadge: Record<string, string> = {
  fail: 'bg-red-100 text-red-800 border-red-200',
  warn: 'bg-amber-100 text-amber-800 border-amber-200',
  info: 'bg-blue-100 text-blue-800 border-blue-200',
  pass: 'bg-emerald-100 text-emerald-800 border-emerald-200',
}

export default function FindingCard({ finding, pdfUrl, defaultOpen = false }: Props) {
  const [open, setOpen] = useState(defaultOpen)
  const loc = finding.evidence_location ?? null

  const canShowViewer = Boolean(pdfUrl && loc?.page)
  const regions: AnnotationRegion[] = loc?.bbox
    ? [{ bbox: loc.bbox, kind: 'finding', label: finding.code_ref }]
    : []

  return (
    <div className="border border-slate-200 rounded-lg overflow-hidden bg-white shadow-sm">
      {/* Header — collapsed view */}
      <button
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-start gap-3 p-3 text-left hover:bg-slate-50 transition-colors"
      >
        <span className={`text-xs font-semibold px-2 py-0.5 rounded border capitalize flex-shrink-0 mt-0.5 ${statusBadge[finding.status] ?? 'bg-slate-100 text-slate-600'}`}>
          {finding.status}
        </span>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap mb-0.5">
            <span className="font-mono text-xs text-blue-700 font-semibold">{finding.code_ref}</span>
            <span className={`text-[10px] font-medium px-1.5 py-0.5 rounded border capitalize ${severityBadge[finding.severity] ?? 'bg-slate-100 text-slate-600'}`}>
              {finding.severity}
            </span>
            {finding.citation_unverified && (
              <span
                className="text-[10px] font-medium px-1.5 py-0.5 rounded border bg-amber-50 text-amber-800 border-amber-300"
                title="Corpus citation gate did not find a high-similarity match — confirm against the cited section before sending."
              >
                Citation unverified
              </span>
            )}
            {loc?.page && (
              <span className="text-[10px] text-slate-400">
                p.{loc.page}{loc.sheet ? ` · ${loc.sheet}` : ''}
              </span>
            )}
          </div>
          <p className="text-sm text-slate-700 leading-snug">{finding.summary}</p>
        </div>
        <svg
          className={`w-4 h-4 text-slate-400 flex-shrink-0 mt-1 transition-transform ${open ? 'rotate-180' : ''}`}
          fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}
        >
          <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {/* Expanded — finding details + PDF region */}
      {open && (
        <div className="border-t border-slate-100 grid grid-cols-1 md:grid-cols-5 gap-4 p-4">
          {/* Left: details (3/5) */}
          <div className="md:col-span-3 space-y-3 min-w-0">
            <p className="text-xs text-slate-600 leading-relaxed">{finding.description}</p>

            {finding.evidence && finding.evidence.length > 0 && (
              <div>
                <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-1.5">Match details</p>
                <ul className="space-y-1">
                  {finding.evidence.map((e, i) => (
                    <li key={i} className="text-xs text-slate-600 flex gap-1.5 items-start">
                      <span className="text-slate-300 flex-shrink-0">▸</span>
                      <span className="break-words">{e}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {loc?.text && (
              <div>
                <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-1.5">Evidence on plan</p>
                <blockquote className="text-xs text-slate-700 border-l-2 border-slate-300 pl-2 italic">
                  &ldquo;{loc.text}&rdquo;
                </blockquote>
              </div>
            )}

            {finding.citation && (
              <div className="bg-blue-50 border border-blue-200 rounded-md p-2.5">
                <p className="text-xs font-semibold text-blue-700 mb-1.5">
                  Citation
                  <span className="ml-2 text-[10px] font-normal text-blue-500">
                    {Math.round((finding.citation.confidence ?? 0) * 100)}% confidence
                  </span>
                </p>
                <blockquote className="text-xs text-blue-900 italic leading-relaxed border-l-2 border-blue-300 pl-2">
                  &ldquo;{finding.citation.text}&rdquo;
                </blockquote>
                {finding.citation.source_url && (
                  <a
                    href={finding.citation.source_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="mt-1.5 text-xs text-blue-600 hover:text-blue-800 inline-block"
                  >
                    {finding.citation.source_title} ↗
                  </a>
                )}
                {finding.citation.notes && (
                  <p className="mt-1 text-[10px] text-blue-500">{finding.citation.notes}</p>
                )}
              </div>
            )}

            <div className="text-[10px] text-slate-400">
              {Math.round(finding.confidence * 100)}% pipeline confidence · rule {finding.rule_id}
            </div>
          </div>

          {/* Right: PDF viewer (2/5) */}
          <div className="md:col-span-2 min-w-0">
            {canShowViewer ? (
              <PdfAnnotationViewer
                pdfUrl={pdfUrl!}
                page={loc!.page!}
                regions={regions}
                width={360}
              />
            ) : (
              <div className="bg-slate-50 border border-slate-200 rounded p-4 text-center text-xs text-slate-400 h-full flex items-center justify-center">
                {!pdfUrl
                  ? 'PDF preview unavailable — no file URL provided.'
                  : !loc?.page
                    ? 'No page location attached — finding is text-only.'
                    : 'No bounding box — page indicated but region unknown.'}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
