import { redirect } from 'next/navigation'
import { createClient } from '@/lib/supabase/server'
import type { AgencyMember, Submittal, TriageRun, ReviewComment } from '@/lib/supabase/types'

export default async function AnalyticsPage() {
  const supabase = await createClient()
  const { data: { user } } = await supabase.auth.getUser()
  if (!user) redirect('/login')

  const { data: memberRaw } = await supabase
    .from('agency_members')
    .select('agency_id')
    .eq('user_id', user.id)
    .limit(1)
    .single()

  const member = memberRaw as AgencyMember | null
  if (!member) redirect('/login')

  const agencyId = member.agency_id

  const [
    { count: totalCount },
    { count: thisMonthCount },
    { data: avgDataRaw },
    { data: triageCostRaw },
    { data: commentsRaw },
  ] = await Promise.all([
    supabase.from('submittals').select('*', { count: 'exact', head: true }).eq('agency_id', agencyId),
    supabase.from('submittals').select('*', { count: 'exact', head: true })
      .eq('agency_id', agencyId)
      .gte('received_at', new Date(new Date().getFullYear(), new Date().getMonth(), 1).toISOString()),
    supabase.from('submittals').select('completeness_score').eq('agency_id', agencyId).not('completeness_score', 'is', null),
    supabase.from('triage_runs').select('llm_cost_usd, duration_ms').eq('agency_id', agencyId),
    supabase.from('review_comments').select('origin').eq('agency_id', agencyId),
  ])

  const avgData = (avgDataRaw ?? []) as Pick<Submittal, 'completeness_score'>[]
  const triageCost = (triageCostRaw ?? []) as Pick<TriageRun, 'llm_cost_usd' | 'duration_ms'>[]
  const commentsData = (commentsRaw ?? []) as Pick<ReviewComment, 'origin'>[]

  const scores = avgData.map(r => r.completeness_score ?? 0).filter(Boolean)
  const avgScore = scores.length ? Math.round(scores.reduce((a, b) => a + b, 0) / scores.length) : null

  const totalCost = triageCost.reduce((sum, r) => sum + (r.llm_cost_usd ?? 0), 0)
  const avgDuration = triageCost.length
    ? Math.round(triageCost.reduce((sum, r) => sum + (r.duration_ms ?? 0), 0) / triageCost.length / 1000)
    : null

  const totalComments = commentsData.length
  const aiComments = commentsData.filter(c => c.origin !== 'human').length

  const stats = [
    { label: 'Total submittals', value: String(totalCount ?? 0), sub: `${thisMonthCount ?? 0} this month` },
    { label: 'Avg completeness score', value: avgScore != null ? String(avgScore) : '—', sub: 'across triaged submittals' },
    { label: 'Avg triage time', value: avgDuration != null ? `${avgDuration}s` : '—', sub: 'AI pipeline' },
    { label: 'AI-drafted comments', value: String(aiComments), sub: totalComments ? `${Math.round(aiComments / totalComments * 100)}% of all comments` : 'none yet' },
  ]

  return (
    <div className="fade-in">
      <h1 className="text-lg font-semibold text-slate-900 mb-5">Analytics</h1>

      <div className="grid grid-cols-2 gap-4 mb-8 lg:grid-cols-4">
        {stats.map(s => (
          <div key={s.label} className="bg-white border border-slate-200 rounded-lg p-4 shadow-sm">
            <div className="text-2xl font-bold text-slate-900">{s.value}</div>
            <div className="text-sm font-medium text-slate-700 mt-1">{s.label}</div>
            <div className="text-xs text-slate-400 mt-0.5">{s.sub}</div>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <div className="bg-white border border-slate-200 rounded-lg p-5 shadow-sm">
          <h2 className="text-sm font-semibold text-slate-700 mb-3">LLM Cost</h2>
          <div className="text-2xl font-bold text-slate-900">${totalCost.toFixed(2)}</div>
          <div className="text-xs text-slate-400 mt-1">Total AI spend across all triage runs</div>
        </div>

        <div className="bg-white border border-slate-200 rounded-lg p-5 shadow-sm">
          <h2 className="text-sm font-semibold text-slate-700 mb-3">Comment Adoption</h2>
          {totalComments === 0 ? (
            <p className="text-sm text-slate-400">No comments yet. Review submittals and accept AI drafts to see adoption rates.</p>
          ) : (
            <>
              <div className="text-2xl font-bold text-slate-900">{totalComments}</div>
              <div className="text-xs text-slate-400 mt-1">total comments · {aiComments} AI-assisted</div>
              <div className="w-full bg-slate-100 rounded-full h-2 mt-3">
                <div
                  className="h-2 rounded-full bg-blue-500 score-bar"
                  style={{ width: `${Math.round(aiComments / totalComments * 100)}%` }}
                />
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
