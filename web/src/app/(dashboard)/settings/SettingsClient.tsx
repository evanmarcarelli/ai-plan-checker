'use client'

import { useState } from 'react'
import { createClient } from '@/lib/supabase/client'
import type { Agency, AgencyMember, MemberRole } from '@/lib/supabase/types'

interface Props {
  agency: Agency
  members: AgencyMember[]
  currentUserId: string
}

function roleBadge(r: MemberRole) {
  const map: Record<MemberRole, string> = {
    admin: 'bg-slate-700 text-white',
    supervisor: 'bg-violet-100 text-violet-800',
    reviewer: 'bg-blue-100 text-blue-800',
    intake: 'bg-slate-100 text-slate-700',
  }
  return map[r] ?? ''
}

interface CustomRule {
  id: string
  label: string
  enabled: boolean
}

export default function SettingsClient({ agency, members, currentUserId }: Props) {
  const supabase = createClient()
  const [codeYear, setCodeYear] = useState(agency.code_year)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [rules, setRules] = useState<CustomRule[]>(() => {
    const raw = agency.custom_rules
    if (Array.isArray(raw)) return raw as unknown as CustomRule[]
    return []
  })

  async function saveCodeYear(year: string) {
    setSaving(true)
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    await (supabase.from('agencies') as any).update({ code_year: year }).eq('id', agency.id)
    setSaving(false)
    setSaved(true)
    setTimeout(() => setSaved(false), 2000)
  }

  function toggleRule(id: string) {
    setRules(rs => rs.map(r => r.id === id ? { ...r, enabled: !r.enabled } : r))
  }

  return (
    <div className="fade-in max-w-3xl">
      <h1 className="text-lg font-semibold text-slate-900 mb-5">Agency Settings</h1>

      {/* Agency info */}
      <div className="bg-white border border-slate-200 rounded-lg p-5 mb-4 shadow-sm">
        <h2 className="text-sm font-semibold text-slate-700 mb-3">Agency</h2>
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded bg-blue-700 flex items-center justify-center text-white font-bold text-sm">
            {agency.name.slice(0, 2).toUpperCase()}
          </div>
          <div>
            <div className="font-semibold text-slate-900">{agency.name}</div>
            <div className="text-xs text-slate-400">
              {agency.city}, {agency.state} · Plan: {agency.plan} · ID: {agency.id.slice(0, 8)}
            </div>
          </div>
        </div>
      </div>

      {/* Code year */}
      <div className="bg-white border border-slate-200 rounded-lg p-5 mb-4 shadow-sm">
        <h2 className="text-sm font-semibold text-slate-700 mb-3">IBC Code Year</h2>
        <div className="flex gap-2">
          {['2018', '2021', '2024'].map(y => (
            <button
              key={y}
              onClick={() => { setCodeYear(y); saveCodeYear(y) }}
              className={`px-5 py-2 rounded border text-sm font-medium transition-colors ${
                codeYear === y
                  ? 'border-blue-600 bg-blue-50 text-blue-700'
                  : 'border-slate-200 text-slate-600 hover:bg-slate-50'
              }`}
            >
              {y} IBC
            </button>
          ))}
          {saving && <span className="text-xs text-slate-400 self-center ml-2">Saving…</span>}
          {saved && <span className="text-xs text-emerald-600 self-center ml-2">Saved</span>}
        </div>
        <p className="text-xs text-slate-400 mt-2">Applies to all triage runs and code citation lookups for this agency.</p>
      </div>

      {/* Custom rules */}
      <div className="bg-white border border-slate-200 rounded-lg p-5 mb-4 shadow-sm">
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-sm font-semibold text-slate-700">Custom Rules & Overrides</h2>
        </div>
        {rules.length === 0 ? (
          <p className="text-sm text-slate-400">No custom rules configured for this agency yet.</p>
        ) : (
          <div className="space-y-3">
            {rules.map(r => (
              <div key={r.id} className="flex items-center justify-between py-2 border-b border-slate-50 last:border-0">
                <span className="text-sm text-slate-700 mr-4">{r.label}</span>
                <button
                  onClick={() => toggleRule(r.id)}
                  className={`relative inline-flex h-5 w-9 flex-shrink-0 rounded-full border-2 border-transparent transition-colors duration-200 ${
                    r.enabled ? 'bg-blue-600' : 'bg-slate-200'
                  }`}
                >
                  <span className={`pointer-events-none inline-block h-4 w-4 rounded-full bg-white shadow transform transition duration-200 ${
                    r.enabled ? 'translate-x-4' : 'translate-x-0'
                  }`} />
                </button>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Members */}
      <div className="bg-white border border-slate-200 rounded-lg p-5 shadow-sm">
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-sm font-semibold text-slate-700">Members ({members.length})</h2>
        </div>
        <div className="space-y-1">
          {members.map(m => (
            <div key={m.id} className="flex items-center justify-between py-2">
              <div className="flex items-center gap-3">
                <div className="w-7 h-7 rounded-full bg-slate-200 flex items-center justify-center text-xs font-semibold text-slate-600">
                  {(m.display_name ?? '?').slice(0, 2).toUpperCase()}
                </div>
                <div>
                  <div className="text-sm font-medium text-slate-800">
                    {m.display_name ?? '(no name)'}
                    {m.user_id === currentUserId && <span className="text-xs text-slate-400 ml-2">you</span>}
                  </div>
                </div>
              </div>
              <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${roleBadge(m.role)}`}>
                {m.role}
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
