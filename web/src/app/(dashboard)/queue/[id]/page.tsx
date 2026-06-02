import { notFound, redirect } from 'next/navigation'
import Link from 'next/link'
import { createClient } from '@/lib/supabase/server'
import type { Submittal, TriageRun, ReviewComment, TriageReport, TriageFinding } from '@/lib/supabase/types'
import CommentComposer from './CommentComposer'
import FindingCard, { type FindingForCard } from '@/components/FindingCard'

// 1 hour signed URL — long enough to span a reviewer session, short enough
// to limit blast radius if a URL leaks. The viewer re-fetches on reload.
const PDF_SIGN_TTL_SECONDS = 60 * 60

// Translate the backend TriageFinding shape into the standalone
// FindingForCard contract that the new card component expects.
// Most fields map directly; we synthesize `status`/`severity` defensively
// because TriageFinding has historically misnamed those.
function toFindingForCard(f: TriageFinding): FindingForCard {
  const status: FindingForCard['status'] =
    f.status ??
    (f.severity === 'fail' || f.severity === 'warning' || f.severity === 'pass' || f.severity === 'info'
      ? (f.severity === 'warning' ? 'warn' : f.severity)
      : 'info')
  const severity = f.severity_tier
    ?? (status === 'fail' ? 'critical' : status === 'warn' ? 'moderate' : 'minor')
  return {
    rule_id: f.rule_id,
    code_ref: f.code_ref,
    description: f.description,
    discipline: f.discipline,
    severity,
    status,
    summary: f.summary ?? f.description,
    evidence: f.evidence,
    confidence: f.confidence,
    evidence_location: f.evidence_location ?? null,
    citation_unverified: f.citation_unverified,
    citation: f.citation,
  }
}

function scoreColor(s: number | null) {
  if (!s) return { text: 'text-slate-500', bar: 'bg-slate-300' }
  if (s >= 80) return { text: 'text-emerald-700', bar: 'bg-emerald-500' }
  if (s >= 50) return { text: 'text-amber-700', bar: 'bg-amber-400' }
  return { text: 'text-red-700', bar: 'bg-red-500' }
}

function statusLabel(s: string) {
  const map: Record<string, string> = {
    received: 'Received', triaging: 'Triaging…', triaged: 'Triaged',
    in_review: 'In Review', on_hold: 'On Hold',
    approved: 'Approved', denied: 'Denied', returned_incomplete: 'Returned',
  }
  return map[s] ?? s
}

export default async function SubmittalDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params
  const supabase = await createClient()

  const { data: { user } } = await supabase.auth.getUser()
  if (!user) redirect('/login')

  const { data: submittalRaw } = await supabase
    .from('submittals')
    .select('*')
    .eq('id', id)
    .single()

  const submittal = submittalRaw as Submittal | null
  if (!submittal) notFound()

  const { data: triageRunRaw } = await supabase
    .from('triage_runs')
    .select('*')
    .eq('submittal_id', id)
    .order('started_at', { ascending: false })
    .limit(1)
    .maybeSingle()

  const triageRun = triageRunRaw as TriageRun | null

  const { data: commentsRaw } = await supabase
    .from('review_comments')
    .select('*')
    .eq('submittal_id', id)
    .order('display_order')

  const comments = (commentsRaw ?? []) as ReviewComment[]

  // Pull the primary submittal file (most recently uploaded) and mint a
  // signed Storage URL so the FindingCard's PDF viewer can render the
  // page that holds each finding's evidence_location. Failing silently
  // is the right call here — when there's no PDF, the viewer renders a
  // "preview unavailable" empty state and the rest of the page still works.
  const { data: primaryFileRaw } = await supabase
    .from('submittal_files')
    .select('storage_path')
    .eq('submittal_id', id)
    .order('created_at', { ascending: false })
    .limit(1)
    .maybeSingle()

  let pdfUrl: string | null = null
  const primaryFile = primaryFileRaw as { storage_path: string } | null
  if (primaryFile?.storage_path) {
    const { data: signed } = await supabase
      .storage
      .from('submittals')
      .createSignedUrl(primaryFile.storage_path, PDF_SIGN_TTL_SECONDS)
    pdfUrl = signed?.signedUrl ?? null
  }

  const report = triageRun?.report as TriageReport | null
  const findings: TriageFinding[] = report?.findings ?? []
  const c = scoreColor(submittal.completeness_score)

  return (
    <div className="fade-in">
      <Link href="/queue" className="flex items-center gap-1.5 text-sm text-blue-600 hover:text-blue-800 mb-4 transition-colors">
        ← Back to Queue
      </Link>

      {/* Header card */}
      <div className="bg-white border border-slate-200 rounded-lg p-5 mb-4 shadow-sm">
        <div className="flex items-start justify-between">
          <div>
            <div className="flex items-center gap-2 mb-1">
              <span className="font-mono text-xs text-slate-400">
                {submittal.external_ref ?? submittal.id.slice(0, 8).toUpperCase()}
              </span>
              <span className="text-xs font-medium px-2 py-0.5 rounded-full bg-blue-100 text-blue-800">
                {statusLabel(submittal.status)}
              </span>
            </div>
            <h2 className="text-xl font-semibold text-slate-900">{submittal.project_name ?? '(unnamed)'}</h2>
            <p className="text-sm text-slate-500 mt-1">
              {[submittal.applicant_name, submittal.project_type, `received ${new Date(submittal.received_at).toLocaleDateString()}`]
                .filter(Boolean).join(' · ')}
            </p>
            {submittal.project_address && (
              <p className="text-sm text-slate-400 mt-0.5">{submittal.project_address}</p>
            )}
          </div>
          <div className="text-right flex-shrink-0 ml-4">
            <div className="text-xs text-slate-500 mb-1">Completeness Score</div>
            <div className={`text-2xl font-bold ${c.text}`}>
              {submittal.completeness_score != null
                ? <>{Math.round(submittal.completeness_score)}<span className="text-base font-normal text-slate-400">/100</span></>
                : <span className="text-slate-400 text-base font-normal">Pending triage</span>
              }
            </div>
            {submittal.completeness_score != null && (
              <div className="w-32 bg-slate-100 rounded-full h-2 mt-2 ml-auto">
                <div className={`h-2 rounded-full score-bar ${c.bar}`} style={{ width: `${submittal.completeness_score}%` }} />
              </div>
            )}
          </div>
        </div>

        {report?.completeness_judgment && (
          <p className="mt-3 text-sm text-slate-600 bg-slate-50 border border-slate-200 rounded px-3 py-2">
            {report.completeness_judgment}
          </p>
        )}
      </div>

      {/* Findings + Comments split */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-5">
        <div className="lg:col-span-3">
          <div className="flex items-center gap-2 mb-3">
            <h3 className="text-sm font-semibold text-slate-700">
              Findings
              {findings.length > 0 && (
                <span className="ml-2 text-xs bg-slate-100 text-slate-500 px-1.5 py-0.5 rounded-full font-normal">
                  {findings.length}
                </span>
              )}
            </h3>
            {triageRun && (
              <span className="text-xs text-slate-400">
                {triageRun.findings_fail} fail · {triageRun.findings_warn} warn · {triageRun.findings_pass} pass
              </span>
            )}
          </div>

          {findings.length === 0 && (
            <div className="bg-white border border-slate-200 rounded-lg p-8 text-center text-slate-400 text-sm shadow-sm">
              {triageRun
                ? 'No findings — submittal appears complete.'
                : 'No triage run yet. Upload a PDF and trigger process-submittal to populate findings.'}
            </div>
          )}

          <div className="space-y-2">
            {findings.map(f => (
              <div key={f.rule_id}>
                <FindingCard finding={toFindingForCard(f)} pdfUrl={pdfUrl} />
                {f.draft_comment && (
                  <div className="mt-1 pl-3">
                    <CommentComposer finding={f} submittalId={id} />
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>

        <div className="lg:col-span-2">
          <h3 className="text-sm font-semibold text-slate-700 mb-3">
            Comments
            {comments.length > 0 && (
              <span className="ml-2 text-xs bg-slate-100 text-slate-500 px-1.5 py-0.5 rounded-full font-normal">
                {comments.length}
              </span>
            )}
          </h3>

          {comments.length === 0 ? (
            <div className="bg-white border border-slate-200 rounded-lg p-6 text-sm text-slate-400 shadow-sm">
              No comments finalized. Accept drafted comments from findings.
            </div>
          ) : (
            <div className="space-y-2">
              {comments.map(comment => (
                <div key={comment.id} className="bg-white border border-slate-200 rounded-lg p-4 shadow-sm">
                  <div className="flex items-center gap-2 mb-1.5">
                    <span className="font-mono text-xs text-blue-700 font-semibold">{comment.code_ref}</span>
                    {comment.origin !== 'human' && (
                      <span className="text-xs bg-blue-50 text-blue-600 border border-blue-200 px-1.5 py-0.5 rounded">
                        AI{comment.origin === 'ai_edited' ? ' (edited)' : ''}
                      </span>
                    )}
                  </div>
                  <p className="text-sm text-slate-700 leading-relaxed">{comment.body}</p>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
