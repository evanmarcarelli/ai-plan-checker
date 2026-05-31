"use client";

// Public marketing landing page. The dashboard is behind /dashboard (auth-
// required) — this page exists to brand, build credibility, show what the
// product does, and convert visitors into signups.
//
// Pricing strategy here: pay-per-use credit packs. One credit = one analysis.
// $1.80 base ≈ 3× the ~$0.60 API cost (cold/warm-cache blended). Volume
// discounts amortize Stripe's flat $0.30/transaction fee.
import Link from "next/link";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  Building2, Sparkles, Zap, ShieldCheck, FileCheck, Flame, Bolt,
  Wrench, Accessibility, Leaf, MapPin, Users, BookOpen, CheckCircle2,
  AlertTriangle, ArrowRight,
} from "lucide-react";
import { createClient } from "@/lib/supabase/client";
import { createPackCheckoutSession, type PackSize } from "@/lib/api";
import InteractiveDemo from "@/components/demo/InteractiveDemo";
import Reveal from "@/components/Reveal";

// ────────────────────────────────────────────────────────────────────
// Pricing model. Pay-per-use. Single source of truth — change here only.
//
// Endpoints set by the founder: 1 check = $60, 100 checks = $2,999. The
// in-between tiers are linearly interpolated by quantity:
//     price(qty) = $60 + (qty − 1) × ($2,999 − $60) / 99
// rounded to whole dollars. The per-check rate now drops from $60 down
// to $29.99 across the ladder — a real volume discount that pushes
// buyers up to the bigger packs.
// ────────────────────────────────────────────────────────────────────
const PRICING = [
  { credits: 1,   price:   60, per: 60.00, label: "Try one"             },
  { credits: 5,   price:  179, per: 35.80, label: "Single project"      },
  { credits: 25,  price:  772, per: 30.88, label: "Firm pack", highlight: true },
  { credits: 100, price: 2999, per: 29.99, label: "Annual / enterprise" },
];

export default function MarketingHome() {
  const [isAuthed, setIsAuthed] = useState<boolean | null>(null);

  useEffect(() => {
    const sb = createClient();
    sb.auth.getSession().then(({ data: { session } }) => {
      setIsAuthed(!!session);
    }).catch(() => setIsAuthed(false));
  }, []);

  // No auto-redirect: the home page is the home page for authed AND unauth
  // users. The nav exposes an explicit "Dashboard" link so authed visitors
  // can hop to the product when they want to — but they're not yanked off
  // the home page on every visit.

  return (
    <div style={{ background: "var(--bg)" }}>
      <Nav isAuthed={isAuthed} />
      <Hero />
      <CredibilityBar />
      <DemoSection />
      <HowItWorks />
      <AgentGrid />
      <Pricing />
      <FinalCta />
      <Disclaimer />
    </div>
  );
}

// ─────────────────────── Nav ───────────────────────

function Nav({ isAuthed }: { isAuthed: boolean | null }) {
  return (
    <header
      className="sticky top-0 z-30 px-6 py-3 border-b backdrop-blur"
      style={{ background: "rgba(255,255,255,0.85)", borderColor: "var(--border)" }}
    >
      <div className="max-w-6xl mx-auto flex items-center justify-between">
        <Link href="/" className="flex items-center gap-2">
          <div
            className="inline-flex items-center justify-center w-8 h-8 rounded-lg"
            style={{ background: "#0B0E14" }}
          >
            <Building2 className="w-4 h-4 text-white" />
          </div>
          <span
            className="font-bold text-base tracking-tight"
            style={{ fontFamily: "var(--font-display)", color: "var(--text-primary)" }}
          >
            Up2Code AI
          </span>
        </Link>

        <nav className="hidden sm:flex items-center gap-6 text-sm" style={{ color: "var(--text-secondary)" }}>
          <a href="#how" className="hover:underline">How it works</a>
          <a href="#demo" className="hover:underline">Demo</a>
          <a href="#pricing" className="hover:underline">Pricing</a>
          <Link href="/feedback" className="hover:underline">Feedback</Link>
        </nav>

        <div className="flex items-center gap-2">
          {isAuthed === false && (
            <>
              <Link
                href="/login?redirect=/dashboard"
                className="text-sm font-medium px-3 py-1.5 rounded-lg"
                style={{ color: "var(--text-secondary)" }}
              >
                Sign in
              </Link>
              <Link
                href="/signup?redirect=/dashboard"
                className="text-sm font-medium px-3 py-1.5 rounded-lg"
                style={{ background: "#0B0E14", color: "#fff" }}
              >
                Get started for free
              </Link>
            </>
          )}
          {isAuthed === true && (
            <Link
              href="/dashboard"
              className="text-sm font-medium px-3 py-1.5 rounded-lg"
              style={{ background: "#0B0E14", color: "#fff" }}
            >
              Open dashboard
            </Link>
          )}
        </div>
      </div>
    </header>
  );
}

// ─────────────────────── Hero ───────────────────────

function Hero() {
  return (
    <section className="px-6 pt-16 pb-12">
      <div className="max-w-4xl mx-auto text-center">
        <div
          className="inline-flex items-center gap-2 text-xs font-medium px-3 py-1.5 rounded-full mb-6"
          style={{ background: "var(--bg-elevated)", border: "1px solid var(--border)", color: "var(--text-secondary)" }}
        >
          <Sparkles className="w-3.5 h-3.5" style={{ color: "var(--accent-bright)" }} />
          90-second pre-submittal code review · grounded in real code text
        </div>

        <h1
          className="text-5xl sm:text-6xl font-bold tracking-tight mb-5"
          style={{ fontFamily: "var(--font-display)", color: "var(--text-primary)", lineHeight: 1.05 }}
        >
          Catch building-code issues<br />
          <span style={{ color: "var(--accent-bright)" }}>before the city does.</span>
        </h1>

        <p
          className="text-lg max-w-2xl mx-auto mb-8"
          style={{ color: "var(--text-secondary)" }}
        >
          Upload a PDF plan set. <strong style={{ color: "var(--text-primary)" }}>12 specialist AI agents</strong> identify
          your jurisdiction and audit it against every code chapter a real city plan check runs. All in 90 seconds.
        </p>

        <div className="flex flex-wrap items-center justify-center gap-3">
          <Link
            href="/signup?redirect=/dashboard"
            className="inline-flex items-center gap-2 px-5 py-3 rounded-xl font-semibold"
            style={{ background: "#0B0E14", color: "#fff" }}
          >
            Run your first check, free
            <ArrowRight className="w-4 h-4" />
          </Link>
          <a
            href="#demo"
            className="inline-flex items-center gap-2 px-5 py-3 rounded-xl font-medium"
            style={{ border: "1px solid var(--border)", color: "var(--text-primary)" }}
          >
            See a sample report
          </a>
        </div>

        <p className="text-xs mt-4" style={{ color: "var(--text-muted)" }}>
          First check free · Monthly plans · Credits roll over
        </p>
      </div>
    </section>
  );
}

// ─────────────────────── Credibility bar ───────────────────────

function CredibilityBar() {
  const stats = [
    { value: "12",  label: "specialist AI agents" },
    { value: "90s", label: "average review time" },
    { value: "100%",label: "citation-verified" },
  ];
  return (
    <section className="px-6 py-8 border-y" style={{ borderColor: "var(--border)", background: "var(--bg-elevated)" }}>
      <div className="max-w-5xl mx-auto grid grid-cols-3 gap-6 text-center">
        {stats.map((s, i) => (
          <Reveal key={s.label} delay={i * 0.06}>
            <div
              className="text-3xl font-bold"
              style={{ fontFamily: "var(--font-display)", color: "var(--text-primary)" }}
            >
              {s.value}
            </div>
            <div className="text-xs uppercase tracking-wide mt-1" style={{ color: "var(--text-muted)" }}>
              {s.label}
            </div>
          </Reveal>
        ))}
      </div>
    </section>
  );
}

// ─────────────────────── Demo (static screenshot mock) ───────────────────────

function DemoSection() {
  return (
    <section id="demo" className="px-6 py-20">
      <div className="max-w-6xl mx-auto">
        <div className="text-center mb-10">
          <p className="text-xs uppercase tracking-widest mb-2" style={{ color: "var(--accent)" }}>
            Live demo
          </p>
          <h2
            className="text-3xl sm:text-4xl font-bold tracking-tight mb-3"
            style={{ fontFamily: "var(--font-display)", color: "var(--text-primary)" }}
          >
            Watch a triage run live.
          </h2>
          <p className="text-base max-w-2xl mx-auto" style={{ color: "var(--text-secondary)" }}>
            Pick a scenario. Up2Code evaluates it against jurisdiction-specific code
            rules and returns a structured compliance report with findings, completeness
            score, and verified citations — in seconds.
          </p>
        </div>

        <InteractiveDemo />

        <div className="text-center mt-8">
          <Link
            href="/signup?redirect=/dashboard"
            className="inline-flex items-center gap-2 text-sm font-medium hover:underline"
            style={{ color: "var(--accent-bright)" }}
          >
            Open the full product
            <ArrowRight className="w-3.5 h-3.5" />
          </Link>
        </div>
      </div>
    </section>
  );
}

// ─────────────────────── How it works ───────────────────────

function HowItWorks() {
  const steps = [
    { n: 1, title: "Upload your plan set",
      body: "Drag in a PDF. Anything from a 5-sheet ADU set to a full commercial submittal." },
    { n: 2, title: "12 agents review in parallel",
      body: "Surveyor identifies jurisdiction. 10 department reviewers run in parallel, each grounded in verbatim code text. ~90 seconds." },
    { n: 3, title: "Get a structured report",
      body: "Compliant, Non-compliant, or Needs review for every finding. Cited section. Concrete recommendation. Sharable with your team or inspector, free for them." },
  ];
  return (
    <section id="how" className="px-6 py-20" style={{ background: "var(--bg-elevated)" }}>
      <div className="max-w-5xl mx-auto">
        <div className="text-center mb-12">
          <p className="text-xs uppercase tracking-widest mb-2" style={{ color: "var(--accent)" }}>
            How it works
          </p>
          <h2
            className="text-3xl sm:text-4xl font-bold tracking-tight"
            style={{ fontFamily: "var(--font-display)", color: "var(--text-primary)" }}
          >
            Three steps. Cancel anytime.
          </h2>
        </div>
        <div className="grid md:grid-cols-3 gap-5">
          {steps.map((s, i) => (
            <Reveal key={s.n} delay={i * 0.08} className="p-6 rounded-xl"
                 style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}>
              <div className="text-xs font-mono mb-3" style={{ color: "var(--accent)" }}>
                {String(s.n).padStart(2, "0")}
              </div>
              <h3 className="font-semibold mb-2" style={{ color: "var(--text-primary)" }}>{s.title}</h3>
              <p className="text-sm leading-relaxed" style={{ color: "var(--text-secondary)" }}>{s.body}</p>
            </Reveal>
          ))}
        </div>
      </div>
    </section>
  );
}

// ─────────────────────── Agent grid ───────────────────────

function AgentGrid() {
  const agents = [
    { Icon: ShieldCheck,   name: "Building & Safety" },
    { Icon: Flame,         name: "Fire" },
    { Icon: Bolt,          name: "Electrical" },
    { Icon: Wrench,        name: "Plumbing" },
    { Icon: Sparkles,      name: "Mechanical" },
    { Icon: Accessibility, name: "Accessibility (ADA)" },
    { Icon: Leaf,          name: "Energy & CALGreen" },
    { Icon: MapPin,        name: "Planning & Zoning" },
    { Icon: Users,         name: "Public Works" },
    { Icon: BookOpen,      name: "Environmental" },
  ];
  return (
    <section className="px-6 py-20">
      <div className="max-w-5xl mx-auto">
        <div className="text-center mb-10">
          <p className="text-xs uppercase tracking-widest mb-2" style={{ color: "var(--accent)" }}>
            Every department a real plan check runs
          </p>
          <h2
            className="text-3xl font-bold tracking-tight"
            style={{ fontFamily: "var(--font-display)", color: "var(--text-primary)" }}
          >
            10 specialist reviewers. One report.
          </h2>
        </div>
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
          {agents.map(({ Icon, name }, i) => (
            <Reveal key={name} delay={i * 0.04}
                 className="flex flex-col items-center justify-center text-center p-4 rounded-xl"
                 style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}>
              <Icon className="w-5 h-5 mb-2" style={{ color: "var(--accent-bright)" }} />
              <div className="text-xs font-medium" style={{ color: "var(--text-primary)" }}>{name}</div>
            </Reveal>
          ))}
        </div>
      </div>
    </section>
  );
}

// ─────────────────────── Pricing ───────────────────────

function Pricing() {
  const router = useRouter();
  const [busyPack, setBusyPack] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function startCheckout(pack: PackSize) {
    setError(null);
    // Authed users go straight to Stripe; everyone else signs up first and
    // lands at /billing?pack=N to resume the same checkout.
    const sb = createClient();
    const { data: { session } } = await sb.auth.getSession();
    if (!session) {
      router.push(`/signup?redirect=/billing?pack=${pack}`);
      return;
    }
    try {
      setBusyPack(pack);
      const { url } = await createPackCheckoutSession(pack);
      window.location.href = url;
    } catch (e) {
      setError(e instanceof Error ? e.message : "Checkout failed");
      setBusyPack(null);
    }
  }

  return (
    <section id="pricing" className="px-6 py-20" style={{ background: "var(--bg-elevated)" }}>
      <div className="max-w-5xl mx-auto">
        <div className="text-center mb-10">
          <p className="text-xs uppercase tracking-widest mb-2" style={{ color: "var(--accent)" }}>
            Pricing
          </p>
          <h2
            className="text-3xl sm:text-4xl font-bold tracking-tight mb-3"
            style={{ fontFamily: "var(--font-display)", color: "var(--text-primary)" }}
          >
            Monthly plans. Credits roll over.
          </h2>
          <p className="text-base max-w-xl mx-auto" style={{ color: "var(--text-secondary)" }}>
            One credit = one full plan review. Unused credits carry to next month. Cancel anytime.
          </p>
        </div>

        <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-4">
          {PRICING.map((p, i) => (
            <Reveal
              key={p.credits}
              delay={i * 0.07}
              className="p-5 rounded-2xl flex flex-col"
              style={{
                background: "var(--bg-card)",
                border: p.highlight ? "2px solid var(--accent-bright)" : "1px solid var(--border)",
              }}
            >
              {p.highlight && (
                <div className="text-[10px] font-bold uppercase tracking-widest mb-2"
                     style={{ color: "var(--accent-bright)" }}>
                  Most popular
                </div>
              )}
              <div className="text-xs uppercase tracking-wide" style={{ color: "var(--text-muted)" }}>
                {p.label}
              </div>
              <div className="mt-2 mb-1 flex items-baseline gap-1">
                <span className="text-3xl font-bold"
                      style={{ fontFamily: "var(--font-display)", color: "var(--text-primary)" }}>
                  ${p.price.toFixed(p.price % 1 === 0 ? 0 : 2)}
                </span>
                <span className="text-sm" style={{ color: "var(--text-muted)" }}>/mo</span>
              </div>
              <div className="text-xs mb-4" style={{ color: "var(--text-secondary)" }}>
                {p.credits === 1
                  ? "1 check / month"
                  : `${p.credits} checks / month · $${p.per.toFixed(2)} each`}
              </div>
              <button
                onClick={() => void startCheckout(p.credits as PackSize)}
                disabled={busyPack !== null}
                className="mt-auto text-center text-sm font-medium py-2 rounded-lg disabled:opacity-60"
                style={{
                  background: p.highlight ? "#0B0E14" : "var(--bg-elevated)",
                  color: p.highlight ? "#fff" : "var(--text-primary)",
                  border: p.highlight ? "none" : "1px solid var(--border)",
                }}
              >
                {busyPack === p.credits ? "Redirecting…" : "Get started"}
              </button>
            </Reveal>
          ))}
        </div>

        {error && (
          <p className="text-center text-xs mt-3" style={{ color: "var(--non-compliant)" }}>
            {error}
          </p>
        )}

        <div className="text-center mt-6 text-xs" style={{ color: "var(--text-muted)" }}>
          Inviting contractors and inspectors to view a report is free. They don&apos;t need a Up2Code account.
        </div>
      </div>
    </section>
  );
}

// ─────────────────────── Final CTA ───────────────────────

function FinalCta() {
  return (
    <section className="px-6 py-24">
      <div className="max-w-3xl mx-auto text-center">
        <h2
          className="text-4xl font-bold tracking-tight mb-4"
          style={{ fontFamily: "var(--font-display)", color: "var(--text-primary)" }}
        >
          Find the corrections before the city does.
        </h2>
        <p className="text-base mb-7" style={{ color: "var(--text-secondary)" }}>
          Your first plan check is on us. Sign up, upload a PDF, and read the report in 90 seconds.
        </p>
        <Link
          href="/signup?redirect=/dashboard"
          className="inline-flex items-center gap-2 px-6 py-3 rounded-xl font-semibold text-base"
          style={{ background: "#0B0E14", color: "#fff" }}
        >
          Run your first check, free
          <ArrowRight className="w-4 h-4" />
        </Link>
      </div>
    </section>
  );
}

// ─────────────────────── Disclaimer ───────────────────────

function Disclaimer() {
  return (
    <div
      className="px-6 py-6 border-t text-center text-xs"
      style={{ borderColor: "var(--border)", background: "var(--bg-elevated)", color: "var(--text-muted)" }}
    >
      <div className="flex items-start justify-center gap-2 max-w-3xl mx-auto">
        <AlertTriangle className="w-3.5 h-3.5 flex-shrink-0 mt-0.5" />
        <p>
          Up2Code AI reports are AI-generated for preliminary review only and are not a substitute for a licensed
          professional or AHJ approval. Always verify findings before relying on them for permit purposes.
        </p>
      </div>
    </div>
  );
}
