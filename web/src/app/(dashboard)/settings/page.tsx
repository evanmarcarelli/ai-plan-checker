import { redirect } from 'next/navigation'
import { createClient } from '@/lib/supabase/server'
import SettingsClient from './SettingsClient'
import type { Agency, AgencyMember } from '@/lib/supabase/types'

export default async function SettingsPage() {
  const supabase = await createClient()
  const { data: { user } } = await supabase.auth.getUser()
  if (!user) redirect('/login')

  const { data: memberRaw } = await supabase
    .from('agency_members')
    .select('*, agencies(*)')
    .eq('user_id', user.id)
    .limit(1)
    .single()

  const member = memberRaw as unknown as (AgencyMember & { agencies: Agency }) | null
  if (!member?.agencies) redirect('/login')

  const { data: membersRaw } = await supabase
    .from('agency_members')
    .select('*')
    .eq('agency_id', member.agency_id)
    .order('created_at')

  const members = (membersRaw ?? []) as AgencyMember[]

  return (
    <SettingsClient
      agency={member.agencies}
      members={members}
      currentUserId={user.id}
    />
  )
}
