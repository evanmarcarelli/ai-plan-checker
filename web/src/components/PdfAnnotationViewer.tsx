'use client'

// =====================================================================
// PdfAnnotationViewer
//
// Renders one page of a PDF (via react-pdf / pdfjs-dist) and draws
// absolute-positioned overlay boxes for findings + ambiguities.
//
// All coordinates are normalized 0..1 in PDF page space, so the boxes
// scale correctly regardless of rendered width.
//
//   Red box    = correction / finding location
//   Yellow box = ambiguity / clarification needed
//
// pdfUrl can be a signed Supabase Storage URL or any same-origin URL.
// The pdf.js worker is loaded from CDN matching the installed
// pdfjs-dist version to keep the Next.js bundle small.
// =====================================================================

import { useState } from 'react'
import { Document, Page, pdfjs } from 'react-pdf'
import 'react-pdf/dist/Page/AnnotationLayer.css'
import 'react-pdf/dist/Page/TextLayer.css'

// Pin worker URL to the installed pdfjs version. If you bump pdfjs-dist
// in package.json the CDN URL updates automatically via pdfjs.version.
if (typeof window !== 'undefined') {
  pdfjs.GlobalWorkerOptions.workerSrc =
    `https://cdnjs.cloudflare.com/ajax/libs/pdf.js/${pdfjs.version}/pdf.worker.min.mjs`
}

export interface AnnotationRegion {
  // Normalized 0..1 coordinates in PDF page space (origin = top-left
  // after react-pdf's default rendering).
  bbox: { x: number; y: number; w: number; h: number }
  kind: 'finding' | 'ambiguity'
  label?: string
}

interface Props {
  pdfUrl: string
  page: number          // 1-indexed PDF page
  regions?: AnnotationRegion[]
  width?: number        // rendered page width in px (default 600)
  onPageCount?: (count: number) => void
}

const STYLE = {
  finding:   { border: '#dc2626', fill: 'rgba(220, 38, 38, 0.15)',  pill: 'bg-red-600 text-white' },
  ambiguity: { border: '#eab308', fill: 'rgba(234, 179, 8, 0.18)', pill: 'bg-yellow-500 text-black' },
} as const

export default function PdfAnnotationViewer({
  pdfUrl, page, regions = [], width = 600, onPageCount,
}: Props) {
  const [error, setError] = useState<string | null>(null)

  return (
    <div className="relative inline-block bg-slate-50 border border-slate-200 rounded overflow-hidden">
      <Document
        file={pdfUrl}
        onLoadSuccess={({ numPages }) => onPageCount?.(numPages)}
        onLoadError={(e) => setError(e?.message ?? 'PDF failed to load')}
        loading={<div className="p-6 text-sm text-slate-400">Loading PDF…</div>}
        error={<div className="p-6 text-sm text-red-600">PDF failed to load{error ? `: ${error}` : ''}</div>}
      >
        <Page
          pageNumber={page}
          width={width}
          renderTextLayer={false}
          renderAnnotationLayer={false}
          loading={<div className="p-6 text-sm text-slate-400">Rendering page {page}…</div>}
        />
      </Document>

      {/* Overlay layer — sized to match the rendered page exactly. */}
      <div className="absolute inset-0 pointer-events-none">
        {regions.map((r, i) => {
          const palette = STYLE[r.kind]
          return (
            <div
              key={i}
              className="absolute"
              style={{
                left: `${r.bbox.x * 100}%`,
                top: `${r.bbox.y * 100}%`,
                width: `${r.bbox.w * 100}%`,
                height: `${r.bbox.h * 100}%`,
                border: `2px solid ${palette.border}`,
                backgroundColor: palette.fill,
              }}
              title={r.label}
            >
              {r.label && (
                <div
                  className={`absolute -top-5 left-0 text-[10px] font-semibold px-1 py-0.5 rounded ${palette.pill}`}
                  style={{ whiteSpace: 'nowrap' }}
                >
                  {r.label}
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
