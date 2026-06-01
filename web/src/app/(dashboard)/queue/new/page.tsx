'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import { createClient } from '@/lib/supabase/client'
import Link from 'next/link'
import type { AgencyMember } from '@/lib/supabase/types'

export default function NewSubmittalPage() {
  const router = useRouter()
  const supabase = createClient()
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [form, setForm] = useState({
    project_name: '',
    project_address: '',
    applicant_name: '',
    applicant_email: '',
    project_type: 'commercial_new',
    external_ref: '',
    scope_of_work: '',
  })

  function set(key: keyof typeof form) {
    return (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) =>
      setForm(f => ({ ...f, [key]: e.target.value }))
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setLoading(true)
    setError('')

    const { data: { user } } = await supabase.auth.getUser()
    if (!user) { setError('Not signed in'); setLoading(false); return }

    const { data: memberRaw } = await supabase
      .from('agency_members')
      .select('agency_id')
      .eq('user_id', user.id)
      .limit(1)
      .single()

    const member = memberRaw as AgencyMember | null
    if (!member) { setError('No agency found'); setLoading(false); return }

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
      setLoading(false)
      return
    }

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
            <input required value={form.project_name} onChange={set('project_name')}
              className="w-full border border-slate-200 rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
          </div>
          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1">Permit / Ref #</label>
            <input value={form.external_ref} onChange={set('external_ref')}
              placeholder="e.g. BLD-2024-0841"
              className="w-full border border-slate-200 rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
          </div>
        </div>

        <div>
          <label className="block text-sm font-medium text-slate-700 mb-1">Project Address</label>
          <input value={form.project_address} onChange={set('project_address')}
            className="w-full border border-slate-200 rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
        </div>

        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1">Applicant Name</label>
            <input value={form.applicant_name} onChange={set('applicant_name')}
              className="w-full border border-slate-200 rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
          </div>
          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1">Applicant Email</label>
            <input type="email" value={form.applicant_email} onChange={set('applicant_email')}
              className="w-full border border-slate-200 rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
          </div>
        </div>

        <div>
          <label className="block text-sm font-medium text-slate-700 mb-1">Project Type</label>
          <select value={form.project_type} onChange={set('project_type')}
            className="w-full border border-slate-200 rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white">
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
          <textarea value={form.scope_of_work} onChange={set('scope_of_work')} rows={3}
            placeholder="Brief description of the proposed work…"
            className="w-full border border-slate-200 rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none" />
        </div>

        {error && (
          <p className="text-sm text-red-600 bg-red-50 border border-red-200 rounded px-3 py-2">{error}</p>
        )}

        <div className="flex gap-3 pt-2">
          <button type="submit" disabled={loading}
            className="bg-blue-600 hover:bg-blue-700 disabled:opacity-60 text-white text-sm px-5 py-2 rounded font-medium transition-colors">
            {loading ? 'Creating…' : 'Create Submittal'}
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
