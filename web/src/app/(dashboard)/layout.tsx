import { redirect } from 'next/navigation'
import { createClient } from '@/lib/supabase/server'
import Nav from '@/components/Nav'
import type { Agency, AgencyMember } from '@/lib/supabase/types'

export default async function DashboardLayout({ children }: { children: React.ReactNode }) {
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

  const navMember = { ...member, email: user.email ?? '' }

  return (
    <div className="min-h-screen bg-slate-50">
      <Nav agency={member.agencies} member={navMember} />
      <main className="max-w-6xl mx-auto px-6 pt-20 pb-10">
        {children}
      </main>
    </div>
  )
}
