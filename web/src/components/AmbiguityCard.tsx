'use client'

// =====================================================================
// AmbiguityCard
//
// Renders one structured ambiguity from BuildingScope.ambiguities.
// Shows the question, the values the extractors saw, and (when an
// evidence_location with a bbox is available) a yellow-highlighted
// PdfAnnotationViewer pane locked to that region.
//
// Reviewers answer via the inline radio/input. Submission calls the
// resolve-ambiguity Edge Function (separate ticket — wires the write
// back into scope and triggers re-triage). Until that ticket lands,
// the answer UI is disabled and shows a tooltip explaining why.
// =====================================================================

import { useState } from 'react'
import PdfAnnotationViewer, { type AnnotationRegion } from './PdfAnnotationViewer'

export interface AmbiguityForCard {
  id: string
  field: string                       // scope field, e.g. "construction_type"
  question: string
  evidence_location?: {
    text: string
    page: number | null
    bbox: { x: number; y: number; w: number; h: number } | null
    sheet?: string | null
  } | null
  llm_value?: unknown
  regex_value?: unknown
  resolved_value?: unknown
  resolved_at?: string | null
}

interface Props {
  ambiguity: AmbiguityForCard
  pdfUrl?: string | null
  // When true, the answer controls are enabled and onResolve is called
  // with the picked value. Default false because the write-back endpoint
  // (resolve-ambiguity) is a separate P3.d ticket — until it lands the
  // card is read-only.
  writeEnabled?: boolean
  onResolve?: (ambiguityId: string, value: unknown) => Promise<void> | void
}

const HUMAN_FIELD: Record<string, string> = {
  occupancies: 'Occupancy',
  occupancy_primary: 'Primary occupancy',
  construction_type: 'Construction type',
  building_area_sf: 'Building area',
  per_story_area_sf: 'Per-story area',
  stories_above: 'Stories above grade',
  height_ft: 'Building height',
  sprinklered: 'Sprinkler status',
  occupant_load: 'Occupant load',
  travel_distance_ft: 'Travel distance',
  mixed_occupancy: 'Mixed-occupancy status',
}

function formatValue(v: unknown): string {
  if (v == null) return '(not stated)'
  if (typeof v === 'boolean') return v ? 'Yes' : 'No'
  if (typeof v === 'number') return String(v)
  if (typeof v === 'string') return v.length > 0 ? v : '(empty)'
  return JSON.stringify(v)
}

export default function AmbiguityCard({
  ambiguity, pdfUrl, writeEnabled = false, onResolve,
}: Props) {
  const loc = ambiguity.evidence_location ?? null
  const resolved = ambiguity.resolved_value !== undefined && ambiguity.resolved_value !== null

  const [picking, setPicking] = useState<'llm' | 'regex' | 'custom' | null>(null)
  const [customText, setCustomText] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')

  const canShowViewer = Boolean(pdfUrl && loc?.page)
  const regions: AnnotationRegion[] = loc?.bbox
    ? [{ bbox: loc.bbox, kind: 'ambiguity', label: HUMAN_FIELD[ambiguity.field] ?? ambiguity.field }]
    : []

  async function handleSubmit() {
    if (!onResolve || !picking) return
    setError('')
    setSubmitting(true)
    try {
      const value =
        picking === 'llm' ? ambiguity.llm_value :
        picking === 'regex' ? ambiguity.regex_value :
        customText
      await onResolve(ambiguity.id, value)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save answer')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="border border-amber-300 bg-amber-50/50 rounded-lg overflow-hidden shadow-sm">
      <div className="px-4 py-3 border-b border-amber-200 bg-amber-100/40 flex items-center gap-2">
        <span className="text-[10px] font-semibold uppercase tracking-wide text-amber-800 bg-amber-200 px-1.5 py-0.5 rounded">
          Needs clarification
        </span>
        <span className="text-xs font-medium text-amber-900">
          {HUMAN_FIELD[ambiguity.field] ?? ambiguity.field}
        </span>
        {resolved && (
          <span className="ml-auto text-[10px] font-medium text-emerald-700 bg-emerald-50 border border-emerald-200 px-1.5 py-0.5 rounded">
            Resolved
          </span>
        )}
      </div>

      <div className="grid grid-cols-1 md:grid-cols-5 gap-4 p-4">
        {/* Left: question + value picker */}
        <div className="md:col-span-3 space-y-3 min-w-0">
          <p className="text-sm text-slate-800 leading-relaxed">{ambiguity.question}</p>

          {!resolved && (
            <div className="space-y-1.5">
              <label className="flex items-start gap-2 text-xs cursor-pointer">
                <input type="radio" name={`amb-${ambiguity.id}`} disabled={!writeEnabled || submitting}
                  checked={picking === 'llm'} onChange={() => setPicking('llm')}
                  className="mt-0.5" />
                <span>
                  <span className="font-medium text-slate-700">AI read:</span>{' '}
                  <code className="text-slate-900 font-mono">{formatValue(ambiguity.llm_value)}</code>
                </span>
              </label>
              <label className="flex items-start gap-2 text-xs cursor-pointer">
                <input type="radio" name={`amb-${ambiguity.id}`} disabled={!writeEnabled || submitting}
                  checked={picking === 'regex'} onChange={() => setPicking('regex')}
                  className="mt-0.5" />
                <span>
                  <span className="font-medium text-slate-700">Regex read:</span>{' '}
                  <code className="text-slate-900 font-mono">{formatValue(ambiguity.regex_value)}</code>
                </span>
              </label>
              <label className="flex items-start gap-2 text-xs cursor-pointer">
                <input type="radio" name={`amb-${ambiguity.id}`} disabled={!writeEnabled || submitting}
                  checked={picking === 'custom'} onChange={() => setPicking('custom')}
                  className="mt-0.5" />
                <span className="flex-1">
                  <span className="font-medium text-slate-700">Other:</span>{' '}
                  <input type="text" placeholder="type the correct value…"
                    value={customText} onChange={e => setCustomText(e.target.value)}
                    onFocus={() => setPicking('custom')}
                    disabled={!writeEnabled || submitting}
                    className="ml-1 border border-slate-200 rounded px-1.5 py-0.5 text-xs w-40 disabled:bg-slate-50" />
                </span>
              </label>
            </div>
          )}

          {resolved && (
            <p className="text-xs text-slate-700">
              <span className="font-medium">Resolved as:</span>{' '}
              <code className="font-mono">{formatValue(ambiguity.resolved_value)}</code>
            </p>
          )}

          {error && (
            <p className="text-xs text-red-700 bg-red-50 border border-red-200 rounded px-2 py-1">{error}</p>
          )}

          {!resolved && (
            <div className="flex items-center gap-2 pt-1">
              <button
                type="button"
                onClick={handleSubmit}
                disabled={!writeEnabled || !picking || submitting || (picking === 'custom' && !customText.trim())}
                title={!writeEnabled ? 'Reviewer write-back lands in P3.d backend ticket — not yet wired.' : ''}
                className="text-xs font-medium px-3 py-1 rounded bg-amber-600 hover:bg-amber-700 disabled:opacity-50 disabled:cursor-not-allowed text-white transition-colors"
              >
                {submitting ? 'Saving…' : 'Submit answer'}
              </button>
              {!writeEnabled && (
                <span className="text-[10px] text-slate-400">read-only preview</span>
              )}
            </div>
          )}

          {loc?.text && (
            <div className="pt-2 border-t border-amber-100">
              <p className="text-[10px] font-semibold text-slate-500 uppercase tracking-wide mb-1">Quoted from plan</p>
              <blockquote className="text-xs text-slate-700 border-l-2 border-amber-300 pl-2 italic">
                &ldquo;{loc.text}&rdquo;
                {loc.page && (
                  <span className="not-italic text-[10px] text-slate-400 ml-2">
                    p.{loc.page}{loc.sheet ? ` · ${loc.sheet}` : ''}
                  </span>
                )}
              </blockquote>
            </div>
          )}
        </div>

        {/* Right: PDF region (yellow box) */}
        <div className="md:col-span-2 min-w-0">
          {canShowViewer ? (
            <PdfAnnotationViewer
              pdfUrl={pdfUrl!}
              page={loc!.page!}
              regions={regions}
              width={300}
            />
          ) : (
            <div className="bg-amber-100/40 border border-amber-200 rounded p-4 text-center text-xs text-amber-700 h-full flex items-center justify-center">
              {!pdfUrl
                ? 'PDF preview unavailable — no file URL.'
                : !loc?.page
                  ? 'No page location attached.'
                  : 'Page known, but no bounding box.'}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
