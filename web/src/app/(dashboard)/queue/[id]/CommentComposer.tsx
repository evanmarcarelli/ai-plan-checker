'use client'

import { useState } from 'react'
import { createClient } from '@/lib/supabase/client'
import type { TriageFinding, AgencyMember } from '@/lib/supabase/types'

interface Props {
  finding: TriageFinding
  submittalId: string
}

export default function CommentComposer({ finding, submittalId }: Props) {
  const [open, setOpen] = useState(false)
  const [text, setText] = useState(finding.draft_comment ?? '')
  const [status, setStatus] = useState<'idle' | 'saving' | 'accepted' | 'rejected'>('idle')
  const supabase = createClient()

  async function getOrCreateReview(agencyId: string, userId: string): Promise<string> {
    const { data: existing } = await supabase
      .from('reviews')
      .select('id')
      .eq('submittal_id', submittalId)
      .eq('reviewer_id', userId)
      .eq('outcome', 'pending')
      .limit(1)
      .maybeSingle()

    const existingReview = existing as { id: string } | null
    if (existingReview) return existingReview.id

    const { data: created } = await supabase
      .from('reviews')
      .insert({ submittal_id: submittalId, agency_id: agencyId, reviewer_id: userId, outcome: 'pending' })
      .select('id')
      .single()

    const createdReview = created as { id: string } | null
    return createdReview!.id
  }

  async function accept() {
    setStatus('saving')
    try {
      const { data: { user } } = await supabase.auth.getUser()
      if (!user) throw new Error('Not signed in')

      const { data: memberRaw } = await supabase
        .from('agency_members')
        .select('agency_id')
        .eq('user_id', user.id)
        .limit(1)
        .single()

      const member = memberRaw as AgencyMember | null
      if (!member) throw new Error('No agency')

      const reviewId = await getOrCreateReview(member.agency_id, user.id)

      const { data: countData } = await supabase
        .from('review_comments')
        .select('id', { count: 'exact', head: true })
        .eq('review_id', reviewId)

      const displayOrder = (countData as unknown as { count?: number })?.count ?? 0
      const wasEdited = text !== finding.draft_comment

      await supabase.from('review_comments').insert({
        review_id: reviewId,
        submittal_id: submittalId,
        agency_id: member.agency_id,
        source_finding_id: finding.rule_id,
        code_ref: finding.code_ref,
        severity: 'correction_required',
        body: text,
        origin: wasEdited ? 'ai_edited' : 'ai_accepted',
        display_order: displayOrder,
        created_by: user.id,
      })

      setStatus('accepted')
      setOpen(false)
    } catch {
      setStatus('idle')
    }
  }

  if (status === 'accepted') return <p className="text-xs text-emerald-600 mt-2">✓ Comment added</p>
  if (status === 'rejected') return <p className="text-xs text-slate-400 mt-2">✗ Rejected</p>

  return (
    <div className="mt-2">
      {!open ? (
        <button
          onClick={() => setOpen(true)}
          className="text-xs bg-blue-50 hover:bg-blue-100 text-blue-700 border border-blue-200 px-3 py-1.5 rounded font-medium transition-colors"
        >
          Draft Comment
        </button>
      ) : (
        <div className="mt-2 bg-slate-50 border border-blue-200 rounded-lg p-3">
          <div className="flex items-center gap-2 mb-2">
            <span className="text-xs font-semibold text-blue-700 bg-blue-50 border border-blue-200 px-2 py-0.5 rounded">AI Draft</span>
            <span className="font-mono text-xs text-slate-500">{finding.code_ref}</span>
          </div>
          <textarea
            className="w-full border border-slate-200 rounded p-2 text-sm text-slate-800 resize-none focus:outline-none focus:ring-2 focus:ring-blue-500 leading-relaxed bg-white"
            rows={4}
            value={text}
            onChange={e => setText(e.target.value)}
          />
          <p className="text-xs text-slate-400 mt-1 mb-2">Reviewer is responsible for verifying accuracy before accepting.</p>
          <div className="flex gap-2">
            <button
              onClick={accept}
              disabled={status === 'saving'}
              className="bg-emerald-600 hover:bg-emerald-700 disabled:opacity-60 text-white text-xs px-3 py-1.5 rounded font-medium transition-colors"
            >
              {status === 'saving' ? 'Saving…' : 'Accept'}
            </button>
            <button
              onClick={() => setText(finding.draft_comment ?? '')}
              className="bg-white hover:bg-slate-50 text-slate-700 border border-slate-300 text-xs px-3 py-1.5 rounded font-medium transition-colors"
            >
              Reset
            </button>
            <button
              onClick={() => { setStatus('rejected'); setOpen(false) }}
              className="text-slate-500 hover:text-slate-700 text-xs px-2 py-1.5 rounded font-medium transition-colors"
            >
              Reject
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
