import Link from 'next/link'
import DemoSection from '@/components/demo/DemoSection'

export default function MarketingPage() {
  return (
    <div className="min-h-screen bg-white">

      {/* ── Sticky header ────────────────────────────────────────────── */}
      <header className="fixed top-0 inset-x-0 z-50 bg-white/90 backdrop-blur-sm border-b border-slate-200/80">
        <div className="max-w-6xl mx-auto px-6 h-14 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="text-slate-900 font-bold text-lg tracking-tight">Plan Room</span>
            <span className="text-xs bg-blue-100 text-blue-700 px-1.5 py-0.5 rounded font-semibold">AHJ</span>
          </div>
          <Link
            href="/login"
            className="text-sm font-medium text-slate-600 hover:text-slate-900 transition-colors"
          >
            Sign in →
          </Link>
        </div>
      </header>

      {/* ── Hero ─────────────────────────────────────────────────────── */}
      <section className="bg-slate-900 pt-32 pb-28 px-6 text-center">
        <div className="max-w-4xl mx-auto">
          {/* Early-access pill */}
          <div className="inline-flex items-center gap-2 text-xs font-medium text-blue-400 bg-blue-400/10 border border-blue-400/20 rounded-full px-3 py-1 mb-8">
            <span className="w-1.5 h-1.5 rounded-full bg-blue-400" />
            Now in early access for CA building departments
          </div>

          <h1 className="text-5xl sm:text-6xl font-bold text-white leading-tight tracking-tight">
            Clear your backlog.<br />
            <span className="text-blue-400">Not your calendar.</span>
          </h1>

          <p className="mt-7 text-xl text-slate-400 leading-relaxed max-w-2xl mx-auto">
            Plan Room&apos;s AI pre-screens every submittal for code compliance — completeness
            score, failing findings, verified citations — so your reviewers spend time on
            real plan check, not intake triage.
          </p>
          <p className="mt-3 text-base text-slate-500">
            Most departments cut first-touch review time by 60%.
          </p>

          <div className="mt-10 flex flex-col sm:flex-row items-center justify-center gap-3">
            <a
              href="#demo"
              className="px-6 py-3 bg-blue-600 text-white font-semibold rounded-lg hover:bg-blue-700 transition-colors text-sm w-full sm:w-auto text-center"
            >
              See it in action ↓
            </a>
            <Link
              href="/login"
              className="px-6 py-3 border border-slate-700 text-slate-300 font-medium rounded-lg hover:border-slate-500 hover:text-white transition-colors text-sm w-full sm:w-auto text-center"
            >
              Sign in to your department
            </Link>
          </div>
        </div>
      </section>

      {/* ── Live demo ────────────────────────────────────────────────── */}
      <section id="demo" className="bg-slate-50 py-20 px-6">
        <div className="max-w-5xl mx-auto">
          <div className="text-center mb-10">
            <h2 className="text-3xl font-bold text-slate-900">Watch a triage run live</h2>
            <p className="text-slate-500 mt-2 text-base">
              Pick a scenario. The AI evaluates it against jurisdiction-specific code rules in real time.
            </p>
          </div>
          <DemoSection />
          <p className="text-center text-xs text-slate-400 mt-5">
            All scenarios use pre-indexed CBC, WSBC, LAMC, and SMC code text. No plan PDF required.
          </p>
        </div>
      </section>

      {/* ── How it works ─────────────────────────────────────────────── */}
      <section className="py-20 px-6 bg-white">
        <div className="max-w-5xl mx-auto">
          <h2 className="text-3xl font-bold text-slate-900 text-center mb-14">How Plan Room works</h2>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-10">
            {[
              {
                step: '01',
                title: 'Applicant uploads a plan set',
                body: 'Submitter sends a PDF via your department portal. Plan Room extracts text from every sheet automatically — no manual data entry.',
              },
              {
                step: '02',
                title: 'AI surveys the jurisdiction',
                body: 'The Surveyor resolves your jurisdiction\'s code sources (Municode, CBC, WSBC), property overlays (WUI, FEMA flood, Coastal Zone), and the full applicable rule set.',
              },
              {
                step: '03',
                title: 'Structured triage report',
                body: 'Every submittal gets a completeness score, ordered findings with severity badges, and verified code citations pulled directly from your jurisdiction\'s adopted code.',
              },
            ].map(({ step, title, body }) => (
              <div key={step} className="relative">
                <div className="text-6xl font-black text-slate-100 leading-none mb-4 select-none">
                  {step}
                </div>
                <h3 className="font-semibold text-slate-900 mb-2">{title}</h3>
                <p className="text-sm text-slate-600 leading-relaxed">{body}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── Feature highlights ───────────────────────────────────────── */}
      <section className="py-20 px-6 bg-slate-50">
        <div className="max-w-5xl mx-auto">
          <h2 className="text-3xl font-bold text-slate-900 text-center mb-12">
            Built for real plan check
          </h2>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            {[
              {
                icon: '⚖️',
                title: 'Jurisdiction-aware',
                body: 'Each submittal is reviewed against the right code sources for your city — CBC + LAMC for LA, WSBC + SMC for Seattle. Pasadena rules never contaminate San Jose reviews.',
              },
              {
                icon: '📚',
                title: '1,300+ indexed code sections',
                body: 'CBC, CRC, CMC, CPC, CEC, Title 24, and local amendments are pre-embedded in a vector corpus. Citations are sourced directly — not hallucinated.',
              },
              {
                icon: '🗺️',
                title: 'Automatic GIS overlays',
                body: 'CalFire FHSZ wildfire zones, FEMA flood zones, and CA Coastal Commission boundaries are resolved automatically from the project address. No manual lookup.',
              },
            ].map(({ icon, title, body }) => (
              <div key={title} className="bg-white border border-slate-200 rounded-xl p-6 shadow-sm">
                <div className="text-3xl mb-3">{icon}</div>
                <h3 className="font-semibold text-slate-900 mb-2">{title}</h3>
                <p className="text-sm text-slate-600 leading-relaxed">{body}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── CTA strip ────────────────────────────────────────────────── */}
      <section className="bg-slate-900 py-20 px-6 text-center">
        <div className="max-w-2xl mx-auto">
          <h2 className="text-3xl font-bold text-white mb-3">Ready to clear your queue?</h2>
          <p className="text-slate-400 mb-8 text-base">
            Plan Room is in early access. We&apos;re onboarding CA building departments now.
          </p>
          <a
            href="mailto:hello@planroom.ai?subject=Early%20Access%20Request"
            className="inline-block px-8 py-3.5 bg-blue-600 text-white font-semibold rounded-lg hover:bg-blue-700 transition-colors"
          >
            Request early access →
          </a>
        </div>
      </section>

      {/* ── Footer ───────────────────────────────────────────────────── */}
      <footer className="bg-slate-900 border-t border-slate-800 py-6 px-6">
        <div className="max-w-6xl mx-auto flex flex-col sm:flex-row items-center justify-between gap-2">
          <span className="text-slate-500 text-sm">© 2026 Plan Room. All rights reserved.</span>
          <Link href="/login" className="text-slate-500 text-sm hover:text-slate-300 transition-colors">
            Sign in
          </Link>
        </div>
      </footer>

    </div>
  )
}
