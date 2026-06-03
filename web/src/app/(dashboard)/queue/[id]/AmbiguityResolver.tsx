'use client'

// Thin client wrapper around <AmbiguityCard> that posts the reviewer's
// answer to the resolve-ambiguity Edge Function and refreshes the route
// so the server component re-reads the updated triage_runs.report row.
//
// Kept separate from queue/[id]/page.tsx so the page can stay a server
// component (cheaper render, no client bundle bloat).

import { useRouter } from 'next/navigation'
import { createClient } from '@/lib/supabase/client'
import AmbiguityCard, { type AmbiguityForCard } from '@/components/AmbiguityCard'

interface Props {
  ambiguity: AmbiguityForCard
  pdfUrl: string | null
  submittalId: string
  agencyId: string
}

export default function AmbiguityResolver({ ambiguity, pdfUrl, submittalId, agencyId }: Props) {
  const router = useRouter()
  const supabase = createClient()

  async function onResolve(ambiguityId: string, value: unknown) {
    const { error } = await supabase.functions.invoke('resolve-ambiguity', {
      body: { submittal_id: submittalId, ambiguity_id: ambiguityId, value },
      headers: { 'X-Agency-Id': agencyId },
    })
    if (error) {
      throw new Error(error.message ?? 'resolve-ambiguity failed')
    }
    // Re-fetch the server component so the resolved card flips state
    // and the new findings appear (process-submittal re-triage already
    // ran server-side as part of the edge function).
    router.refresh()
  }

  return (
    <AmbiguityCard
      ambiguity={ambiguity}
      pdfUrl={pdfUrl}
      writeEnabled
      onResolve={onResolve}
    />
  )
}
