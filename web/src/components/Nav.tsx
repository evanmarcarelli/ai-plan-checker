'use client'

import Link from 'next/link'
import { usePathname, useRouter } from 'next/navigation'
import { createClient } from '@/lib/supabase/client'
import type { Agency, AgencyMember } from '@/lib/supabase/types'

interface NavProps {
  agency: Agency
  member: AgencyMember & { email: string }
}

export default function Nav({ agency, member }: NavProps) {
  const pathname = usePathname()
  const router = useRouter()
  const supabase = createClient()

  const initials = (member.display_name ?? member.email)
    .split(/[\s@]+/)
    .slice(0, 2)
    .map(s => s[0]?.toUpperCase() ?? '')
    .join('')

  async function signOut() {
    await supabase.auth.signOut()
    router.push('/login')
  }

  const links = [
    { href: '/queue', label: 'Queue' },
    { href: '/analytics', label: 'Analytics' },
    { href: '/settings', label: 'Settings' },
  ]

  return (
    <header className="bg-slate-900 text-white h-14 flex items-center px-6 gap-6 shadow-lg fixed top-0 left-0 right-0 z-50">
      <span className="font-semibold text-sm tracking-tight mr-2">
        <span className="text-blue-400">Plan Room</span> AHJ
      </span>

      <div className="flex items-center gap-1 bg-slate-800 rounded px-3 py-1 text-xs text-slate-300">
        {agency.name.split('—')[0].trim()}
      </div>

      <nav className="flex gap-1 ml-2">
        {links.map(({ href, label }) => {
          const active = pathname.startsWith(href)
          return (
            <Link
              key={href}
              href={href}
              className={`px-3 py-1 rounded text-sm transition-colors ${
                active ? 'bg-blue-600 text-white' : 'text-slate-400 hover:text-white hover:bg-slate-800'
              }`}
            >
              {label}
            </Link>
          )
        })}
      </nav>

      <div className="ml-auto flex items-center gap-3">
        <span className="text-xs text-slate-400 capitalize">{member.role}</span>
        <button
          onClick={signOut}
          title="Sign out"
          className="w-8 h-8 rounded-full bg-violet-600 flex items-center justify-center text-xs font-semibold hover:bg-violet-500 transition-colors"
        >
          {initials}
        </button>
      </div>
    </header>
  )
}
