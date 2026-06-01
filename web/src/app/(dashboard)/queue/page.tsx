import { redirect } from 'next/navigation'
import Link from 'next/link'
import { createClient } from '@/lib/supabase/server'
import type { AgencyMember, Submittal } from '@/lib/supabase/types'

function scoreColor(s: number | null) {
  if (!s) return { bg: 'bg-slate-100', text: 'text-slate-500', bar: 'bg-slate-300' }
  if (s >= 80) return { bg: 'bg-emerald-100', text: 'text-emerald-800', bar: 'bg-emerald-500' }
  if (s >= 50) return { bg: 'bg-amber-100', text: 'text-amber-800', bar: 'bg-amber-400' }
  return { bg: 'bg-red-100', text: 'text-red-800', bar: 'bg-red-500' }
}

function statusBadge(s: string) {
  const map: Record<string, string> = {
    triaged: 'bg-blue-100 text-blue-800',
    in_review: 'bg-violet-100 text-violet-800',
    received: 'bg-slate-100 text-slate-600',
    triaging: 'bg-yellow-100 text-yellow-800',
    on_hold: 'bg-orange-100 text-orange-800',
    approved: 'bg-emerald-100 text-emerald-800',
    denied: 'bg-red-100 text-red-800',
    returned_incomplete: 'bg-red-100 text-red-700',
  }
  return map[s] ?? 'bg-slate-100 text-slate-600'
}

function statusLabel(s: string) {
  const map: Record<string, string> = {
    received: 'Received', triaging: 'Triaging…', triaged: 'Triaged',
    in_review: 'In Review', on_hold: 'On Hold',
    approved: 'Approved', denied: 'Denied', returned_incomplete: 'Returned',
  }
  return map[s] ?? s
}

export default async function QueuePage() {
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

  const { data: submittalsRaw } = await supabase
    .from('submittals')
    .select('*')
    .eq('agency_id', member.agency_id)
    .not('status', 'in', '("approved","denied")')
    .order('completeness_score', { ascending: true })
    .order('received_at', { ascending: false })
    .limit(100)

  const rows = (submittalsRaw ?? []) as Submittal[]

  return (
    <div className="fade-in">
      <div className="flex items-center justify-between mb-5">
        <div>
          <h1 className="text-lg font-semibold text-slate-900">Submittal Queue</h1>
          <p className="text-sm text-slate-500 mt-0.5">{rows.length} submittals · sorted by completeness score</p>
        </div>
        <Link
          href="/queue/new"
          className="bg-blue-600 hover:bg-blue-700 text-white text-sm px-4 py-2 rounded font-medium transition-colors"
        >
          + New Submittal
        </Link>
      </div>

      <div className="bg-white rounded-lg border border-slate-200 overflow-hidden shadow-sm">
        {rows.length === 0 ? (
          <div className="px-6 py-16 text-center text-slate-400 text-sm">
            No active submittals. Create one to get started.
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-slate-50 border-b border-slate-200">
                <th className="text-left px-4 py-3 font-medium text-slate-600 text-xs uppercase tracking-wide">ID</th>
                <th className="text-left px-4 py-3 font-medium text-slate-600 text-xs uppercase tracking-wide">Project</th>
                <th className="text-left px-4 py-3 font-medium text-slate-600 text-xs uppercase tracking-wide">Type</th>
                <th className="text-left px-4 py-3 font-medium text-slate-600 text-xs uppercase tracking-wide">Received</th>
                <th className="text-left px-4 py-3 font-medium text-slate-600 text-xs uppercase tracking-wide">Score</th>
                <th className="text-left px-4 py-3 font-medium text-slate-600 text-xs uppercase tracking-wide">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {rows.map(row => {
                const c = scoreColor(row.completeness_score)
                return (
                  <tr key={row.id} className="hover:bg-blue-50 transition-colors">
                    <td className="px-4 py-3 font-mono text-xs text-slate-500">
                      <Link href={`/queue/${row.id}`} className="hover:text-blue-600">
                        {row.external_ref ?? row.id.slice(0, 8).toUpperCase()}
                      </Link>
                    </td>
                    <td className="px-4 py-3">
                      <Link href={`/queue/${row.id}`} className="block hover:text-blue-700">
                        <div className="font-medium text-slate-900">{row.project_name ?? '(unnamed)'}</div>
                        <div className="text-xs text-slate-400 mt-0.5">{row.applicant_name ?? '—'}</div>
                      </Link>
                    </td>
                    <td className="px-4 py-3 text-slate-500 text-xs">{row.project_type ?? '—'}</td>
                    <td className="px-4 py-3 text-slate-500 text-xs">
                      {new Date(row.received_at).toLocaleDateString()}
                    </td>
                    <td className="px-4 py-3">
                      {row.completeness_score != null ? (
                        <div className="flex items-center gap-2">
                          <div className="w-16 bg-slate-100 rounded-full h-1.5">
                            <div
                              className={`h-1.5 rounded-full score-bar ${c.bar}`}
                              style={{ width: `${row.completeness_score}%` }}
                            />
                          </div>
                          <span className={`text-xs font-semibold px-1.5 py-0.5 rounded ${c.bg} ${c.text}`}>
                            {Math.round(row.completeness_score)}
                          </span>
                        </div>
                      ) : (
                        <span className="text-xs text-slate-400">—</span>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      <span className={`text-xs font-medium px-2 py-1 rounded-full ${statusBadge(row.status)}`}>
                        {statusLabel(row.status)}
                      </span>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
