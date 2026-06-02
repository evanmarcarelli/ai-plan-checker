'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import { createClient } from '@/lib/supabase/client'
import Link from 'next/link'
import type { AgencyMember } from '@/lib/supabase/types'

// Caps the upload at 50MB. Plan sets above this size are usually scanned
// scans (raster TIFFs masquerading as PDFs) and need OCR anyway — kicking
// those into Textract is a separate ticket. The Edge Function also has
// memory caps that this stays comfortably under.
const MAX_FILE_BYTES = 50 * 1024 * 1024
const STORAGE_BUCKET = 'submittals'

// Progress states the user sees in the submit button + status line.
// Linear; each step waits for the prior one. On error we drop back to 'idle'.
type Phase = 'idle' | 'creating' | 'uploading' | 'extracting' | 'redirecting'

const PHASE_LABEL: Record<Phase, string> = {
  idle: 'Create Submittal',
  creating: 'Creating submittal…',
  uploading: 'Uploading PDF…',
  extracting: 'Extracting text + coordinates…',
  redirecting: 'Done — opening submittal…',
}

// Slugify a filename for Storage. Keeps it short, ASCII, no spaces or
// path separators. Preserves extension. Storage paths are user-visible
// in download URLs so cleanliness matters.
function safeFilename(name: string): string {
  const lastDot = name.lastIndexOf('.')
  const ext = lastDot > 0 ? name.slice(lastDot + 1).toLowerCase() : 'pdf'
  const stem = (lastDot > 0 ? name.slice(0, lastDot) : name)
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 60) || 'planset'
  return `${stem}.${ext}`
}

export default function NewSubmittalPage() {
  const router = useRouter()
  const supabase = createClient()
  const [phase, setPhase] = useState<Phase>('idle')
  const [error, setError] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [form, setForm] = useState({
    project_name: '',
    project_address: '',
    applicant_name: '',
    applicant_email: '',
    project_type: 'commercial_new',
    external_ref: '',
    scope_of_work: '',
  })

  const loading = phase !== 'idle'

  function set(key: keyof typeof form) {
    return (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) =>
      setForm(f => ({ ...f, [key]: e.target.value }))
  }

  function onFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0] ?? null
    setError('')
    if (f && f.size > MAX_FILE_BYTES) {
      setError(`File too large (${(f.size / 1024 / 1024).toFixed(1)} MB). Max 50 MB.`)
      e.target.value = ''
      setFile(null)
      return
    }
    if (f && f.type && f.type !== 'application/pdf') {
      setError('Only PDF files are supported.')
      e.target.value = ''
      setFile(null)
      return
    }
    setFile(f)
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError('')

    if (!file) { setError('Please attach a PDF planset.'); return }

    const { data: { user } } = await supabase.auth.getUser()
    if (!user) { setError('Not signed in'); return }

    const { data: memberRaw } = await supabase
      .from('agency_members')
      .select('agency_id')
      .eq('user_id', user.id)
      .limit(1)
      .single()

    const member = memberRaw as AgencyMember | null
    if (!member) { setError('No agency found'); return }

    // ── 1. Create the submittal row ───────────────────────────────────
    setPhase('creating')
    const { data: submittalRaw, error: insertError } = await supabase
      .from('submittals')
      .insert({
        agency_id: member.agency_id,
        project_name: form.project_name,
        project_address: form.project_address || null,
        applicant_name: form.applicant_name || null,
        applicant_email: form.applicant_email || null,
        project_type: form.project_type,
        external_ref: form.external_ref || null,
        scope_of_work: form.scope_of_work || null,
        created_by: user.id,
      })
      .select('id')
      .single()

    const submittal = submittalRaw as { id: string } | null
    if (insertError || !submittal) {
      setError(insertError?.message ?? 'Failed to create submittal')
      setPhase('idle')
      return
    }

    // ── 2. Upload PDF to Storage ──────────────────────────────────────
    // Path: <agency_id>/<submittal_id>/<filename>.pdf — matches the
    // pattern documented in supabase/migrations/0001_init.sql comment.
    setPhase('uploading')
    const storagePath = `${member.agency_id}/${submittal.id}/${safeFilename(file.name)}`
    const { error: uploadErr } = await supabase
      .storage
      .from(STORAGE_BUCKET)
      .upload(storagePath, file, {
        cacheControl: '3600',
        contentType: 'application/pdf',
        upsert: false,
      })

    if (uploadErr) {
      setError(`Upload failed: ${uploadErr.message}`)
      setPhase('idle')
      return
    }

    // ── 3. Insert submittal_files row ─────────────────────────────────
    // extract-pdf needs this row to know which Storage path to read.
    const { data: fileRowRaw, error: fileRowErr } = await supabase
      .from('submittal_files')
      .insert({
        submittal_id: submittal.id,
        agency_id: member.agency_id,
        storage_path: storagePath,
        filename: file.name,
        size_bytes: file.size,
        mime_type: 'application/pdf',
        uploaded_by: user.id,
      })
      .select('id')
      .single()

    const fileRow = fileRowRaw as { id: string } | null
    if (fileRowErr || !fileRow) {
      setError(`File record failed: ${fileRowErr?.message ?? 'unknown'}`)
      setPhase('idle')
      return
    }

    // ── 4. Call extract-pdf ───────────────────────────────────────────
    // Populates extracted_text + text_blocks. Without this, the
    // PdfAnnotationViewer renders no bounding boxes and findings have
    // no evidence_location.bbox. Failing here is non-fatal — the user
    // can re-trigger extraction from the queue page later — so we
    // surface a warning and continue to the queue view.
    setPhase('extracting')
    const { error: extractErr } = await supabase.functions.invoke('extract-pdf', {
      body: { submittal_file_id: fileRow.id },
      headers: { 'X-Agency-Id': member.agency_id },
    })

    if (extractErr) {
      console.warn('[new-submittal] extract-pdf failed:', extractErr)
      // Soft-fail: user lands on the queue page anyway with a banner
      // explaining what's missing. They can re-trigger from there.
      setError(`PDF text extraction failed: ${extractErr.message ?? 'unknown'}. Submittal created but annotations will be unavailable. Re-run extract from the queue page.`)
      // Still redirect — the submittal exists and the user shouldn't
      // be stuck on the form.
    }

    setPhase('redirecting')
    router.push(`/queue/${submittal.id}`)
  }

  return (
    <div className="fade-in max-w-2xl">
      <Link href="/queue" className="flex items-center gap-1.5 text-sm text-blue-600 hover:text-blue-800 mb-4 transition-colors">
        ← Back to Queue
      </Link>

      <h1 className="text-lg font-semibold text-slate-900 mb-5">New Submittal</h1>

      <form onSubmit={handleSubmit} className="bg-white border border-slate-200 rounded-lg p-6 shadow-sm space-y-5">
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1">Project Name</label>
            <input required value={form.project_name} onChange={set('project_name')} disabled={loading}
              className="w-full border border-slate-200 rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:bg-slate-50 disabled:text-slate-500" />
          </div>
          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1">Permit / Ref #</label>
            <input value={form.external_ref} onChange={set('external_ref')} disabled={loading}
              placeholder="e.g. BLD-2024-0841"
              className="w-full border border-slate-200 rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:bg-slate-50 disabled:text-slate-500" />
          </div>
        </div>

        <div>
          <label className="block text-sm font-medium text-slate-700 mb-1">Project Address</label>
          <input value={form.project_address} onChange={set('project_address')} disabled={loading}
            className="w-full border border-slate-200 rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:bg-slate-50 disabled:text-slate-500" />
        </div>

        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1">Applicant Name</label>
            <input value={form.applicant_name} onChange={set('applicant_name')} disabled={loading}
              className="w-full border border-slate-200 rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:bg-slate-50 disabled:text-slate-500" />
          </div>
          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1">Applicant Email</label>
            <input type="email" value={form.applicant_email} onChange={set('applicant_email')} disabled={loading}
              className="w-full border border-slate-200 rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:bg-slate-50 disabled:text-slate-500" />
          </div>
        </div>

        <div>
          <label className="block text-sm font-medium text-slate-700 mb-1">Project Type</label>
          <select value={form.project_type} onChange={set('project_type')} disabled={loading}
            className="w-full border border-slate-200 rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white disabled:bg-slate-50 disabled:text-slate-500">
            <option value="commercial_new">Commercial — New Construction</option>
            <option value="commercial_ti">Commercial — Tenant Improvement</option>
            <option value="commercial_addition">Commercial — Addition</option>
            <option value="residential_new">Residential — New Construction</option>
            <option value="residential_addition">Residential — Addition / Alteration</option>
            <option value="industrial">Industrial</option>
            <option value="mixed_use">Mixed Use</option>
            <option value="change_of_occupancy">Change of Occupancy</option>
          </select>
        </div>

        <div>
          <label className="block text-sm font-medium text-slate-700 mb-1">Scope of Work</label>
          <textarea value={form.scope_of_work} onChange={set('scope_of_work')} rows={3} disabled={loading}
            placeholder="Brief description of the proposed work…"
            className="w-full border border-slate-200 rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none disabled:bg-slate-50 disabled:text-slate-500" />
        </div>

        {/* ── PDF picker ──────────────────────────────────────────── */}
        <div>
          <label className="block text-sm font-medium text-slate-700 mb-1">
            Planset PDF <span className="text-red-600">*</span>
          </label>
          <input type="file" accept="application/pdf,.pdf" required onChange={onFileChange} disabled={loading}
            className="w-full border border-slate-200 rounded px-3 py-2 text-sm bg-white file:mr-3 file:px-3 file:py-1 file:rounded file:border-0 file:bg-blue-50 file:text-blue-700 file:text-xs file:font-medium hover:file:bg-blue-100 disabled:opacity-60" />
          {file && (
            <p className="mt-1 text-xs text-slate-500">
              {file.name} · {(file.size / 1024 / 1024).toFixed(1)} MB
            </p>
          )}
          <p className="mt-1 text-xs text-slate-400">
            Max 50 MB. PDF only. Text extraction + bounding boxes run after upload (~5–30 s).
          </p>
        </div>

        {error && (
          <p className="text-sm text-red-600 bg-red-50 border border-red-200 rounded px-3 py-2">{error}</p>
        )}

        {loading && (
          <div className="text-sm text-blue-700 bg-blue-50 border border-blue-200 rounded px-3 py-2 flex items-center gap-2">
            <span className="inline-block w-3 h-3 rounded-full bg-blue-500 animate-pulse" />
            {PHASE_LABEL[phase]}
          </div>
        )}

        <div className="flex gap-3 pt-2">
          <button type="submit" disabled={loading || !file}
            className="bg-blue-600 hover:bg-blue-700 disabled:opacity-60 disabled:cursor-not-allowed text-white text-sm px-5 py-2 rounded font-medium transition-colors">
            {PHASE_LABEL[phase]}
          </button>
          <Link href="/queue"
            className="text-sm text-slate-600 hover:text-slate-800 px-4 py-2 rounded border border-slate-200 hover:bg-slate-50 transition-colors">
            Cancel
          </Link>
        </div>
      </form>
    </div>
  )
}
