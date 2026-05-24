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

// ────────────────────────────────────────────────────────────────────
// Pricing model. Pay-per-use. Single source of truth — change here only.
//
// Endpoints set by the founder: 1 check = $25, 100 checks = $2,999. The
// in-between tiers are linearly interpolated by quantity:
//     price(qty) = $25 + (qty − 1) × (2999 − 25)/99
// rounded to clean numbers. Per-check rate rises slightly with bigger
// packs ($25 → $29.99) — there is no volume discount by design; the
// $25 single-credit price exists as a low-friction trial entry, and the
// $2,999 hundred-pack is the firm/enterprise commitment.
// ────────────────────────────────────────────────────────────────────
const PRICING = [
  { credits: 1,   price:    25, per: 25.00, label: "Try one"             },
  { credits: 5,   price:   149, per: 29.80, label: "Single project"      },
  { credits: 25,  price:   749, per: 29.96, label: "Firm pack", highlight: true },
  { credits: 100, price: 2999,  per: 29.99, label: "Annual / enterprise" },
];

export default function MarketingHome() {
  const router = useRouter();
  const [isAuthed, setIsAuthed] = useState<boolean | null>(null);

  useEffect(() => {
    const sb = createClient();
    sb.auth.getSession().then(({ data: { session } }) => {
      setIsAuthed(!!session);
    }).catch(() => setIsAuthed(false));
  }, []);

  // Authed users get sent straight to the product; the marketing page is for
  // anonymous visitors.
  useEffect(() => {
    if (isAuthed === true) router.replace("/dashboard");
  }, [isAuthed, router]);

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
                Get started — free
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
          your jurisdiction and audit it against every code chapter a real city plan check runs — in 90 seconds.
        </p>

        <div className="flex flex-wrap items-center justify-center gap-3">
          <Link
            href="/signup?redirect=/dashboard"
            className="inline-flex items-center gap-2 px-5 py-3 rounded-xl font-semibold"
            style={{ background: "#0B0E14", color: "#fff" }}
          >
            Run your first check — free
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
          No credit card required · No subscription · Pay per check
        </p>
      </div>
    </section>
  );
}

// ─────────────────────── Credibility bar ───────────────────────

function CredibilityBar() {
  const stats = [
    { value: "12",  label: "specialist AI agents" },
    { value: "86",  label: "verified code sections" },
    { value: "90s", label: "average review time" },
    { value: "100%",label: "citation-verified" },
  ];
  return (
    <section className="px-6 py-8 border-y" style={{ borderColor: "var(--border)", background: "var(--bg-elevated)" }}>
      <div className="max-w-5xl mx-auto grid grid-cols-2 md:grid-cols-4 gap-6 text-center">
        {stats.map((s) => (
          <div key={s.label}>
            <div
              className="text-3xl font-bold"
              style={{ fontFamily: "var(--font-display)", color: "var(--text-primary)" }}
            >
              {s.value}
            </div>
            <div className="text-xs uppercase tracking-wide mt-1" style={{ color: "var(--text-muted)" }}>
              {s.label}
            </div>
          </div>
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
            Sample report
          </p>
          <h2
            className="text-3xl sm:text-4xl font-bold tracking-tight mb-3"
            style={{ fontFamily: "var(--font-display)", color: "var(--text-primary)" }}
          >
            What you get back, every time.
          </h2>
          <p className="text-base max-w-2xl mx-auto" style={{ color: "var(--text-secondary)" }}>
            A structured compliance report with findings categorized by department, citations grounded in real
            code text, and concrete recommendations.
          </p>
        </div>

        <DashboardMockup />

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

function DashboardMockup() {
  return (
    <div
      className="rounded-2xl overflow-hidden shadow-xl"
      style={{ border: "1px solid var(--border)", background: "var(--bg-card)" }}
    >
      {/* Fake browser chrome */}
      <div className="flex items-center gap-1.5 px-4 py-2.5 border-b"
           style={{ borderColor: "var(--border)", background: "var(--bg-elevated)" }}>
        <span className="w-3 h-3 rounded-full" style={{ background: "#FF5F57" }} />
        <span className="w-3 h-3 rounded-full" style={{ background: "#FEBC2E" }} />
        <span className="w-3 h-3 rounded-full" style={{ background: "#28C840" }} />
        <span className="text-xs ml-4" style={{ color: "var(--text-muted)" }}>
          up2code.ai/dashboard — Altadena SFR Rebuild
        </span>
      </div>

      <div className="p-6 grid grid-cols-1 lg:grid-cols-3 gap-5">
        {/* Score ring + summary */}
        <div className="lg:col-span-2 p-5 rounded-xl"
             style={{ background: "var(--bg-elevated)", border: "1px solid var(--border)" }}>
          <div className="flex items-center gap-5">
            <FakeScoreRing score={42} />
            <div className="flex-1">
              <div className="text-lg font-semibold" style={{ color: "var(--text-primary)" }}>
                Compliance Report
              </div>
              <div className="text-xs mb-3" style={{ color: "var(--text-muted)" }}>
                Altadena, CA · 2-story SFR · 2,400 sf
              </div>
              <div className="grid grid-cols-4 gap-2">
                <MiniStat n={2}  label="OK"   color="#10b981" />
                <MiniStat n={5}  label="Crit" color="#ef4444" />
                <MiniStat n={19} label="High" color="#f59e0b" />
                <MiniStat n={51} label="Rev"  color="#64748b" />
              </div>
            </div>
          </div>
        </div>

        {/* Jurisdiction card */}
        <div className="p-5 rounded-xl"
             style={{ background: "var(--bg-elevated)", border: "1px solid var(--border)" }}>
          <div className="flex items-center gap-2 mb-3 text-sm font-semibold"
               style={{ color: "var(--text-primary)" }}>
            <MapPin className="w-4 h-4" style={{ color: "var(--accent-bright)" }} />
            Jurisdiction
          </div>
          <KV k="City"      v="Altadena" />
          <KV k="County"    v="Los Angeles" />
          <KV k="State"     v="California" />
          <KV k="Seismic"   v="Zone D" />
          <KV k="Fire zone" v="VHFHSZ — WUI" warn />
        </div>

        {/* Findings list */}
        <div className="lg:col-span-3 rounded-xl"
             style={{ background: "var(--bg-elevated)", border: "1px solid var(--border)" }}>
          <div className="px-4 py-3 text-xs uppercase tracking-wide border-b"
               style={{ color: "var(--text-muted)", borderColor: "var(--border)" }}>
            Findings (4 of 78 shown)
          </div>
          <div className="divide-y" style={{ borderColor: "var(--border)" }}>
            <FakeFinding
              icon={Flame} dept="Fire" severity="critical"
              section="CBC-7A 704A.1"
              text="Plan shows wood siding within 5 ft of grade; Altadena is in a Very High Fire Hazard Severity Zone — CBC Ch. 7A requires noncombustible siding in the first 5 ft."
            />
            <FakeFinding
              icon={ShieldCheck} dept="Building & Safety" severity="critical"
              section="IFC 1030.2"
              text="Upstairs bedroom 3 window: 16x36 slider w/ 48&quot; sill exceeds 44&quot; max AFF and is under 5.7 sf net clear opening required for emergency escape."
            />
            <FakeFinding
              icon={Leaf} dept="Environmental" severity="high"
              section="T24 150.1(c)14"
              text="No PV system shown on roof plan. California Title 24 requires a sized photovoltaic system on all new SFD."
            />
            <FakeFinding
              icon={Bolt} dept="Electrical" severity="medium"
              section="NEC 210.8(A)"
              text="Two countertop receptacles within 6 ft of sink not annotated GFCI; required for dwelling unit kitchens."
            />
          </div>
        </div>
      </div>
    </div>
  );
}

function FakeScoreRing({ score }: { score: number }) {
  const color = score >= 80 ? "#10b981" : score >= 50 ? "#f59e0b" : "#ef4444";
  const r = 36;
  const c = 2 * Math.PI * r;
  const off = c - c * (score / 100);
  return (
    <div className="relative w-24 h-24">
      <svg width="96" height="96" viewBox="0 0 96 96">
        <circle cx="48" cy="48" r={r} fill="none" stroke="rgba(0,0,0,0.08)" strokeWidth="8" />
        <circle cx="48" cy="48" r={r} fill="none" stroke={color} strokeWidth="8"
                strokeLinecap="round" strokeDasharray={c} strokeDashoffset={off}
                transform="rotate(-90 48 48)" />
      </svg>
      <div className="absolute inset-0 flex items-center justify-center">
        <span className="text-xl font-bold" style={{ color }}>{score}%</span>
      </div>
    </div>
  );
}

function MiniStat({ n, label, color }: { n: number; label: string; color: string }) {
  return (
    <div className="text-center px-2 py-1.5 rounded-md"
         style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}>
      <div className="text-base font-bold" style={{ color }}>{n}</div>
      <div className="text-[10px] uppercase tracking-wide" style={{ color: "var(--text-muted)" }}>{label}</div>
    </div>
  );
}

function KV({ k, v, warn }: { k: string; v: string; warn?: boolean }) {
  return (
    <div className="flex justify-between text-xs py-1">
      <span style={{ color: "var(--text-muted)" }}>{k}</span>
      <span style={{ color: warn ? "var(--non-compliant)" : "var(--text-primary)", fontWeight: warn ? 600 : 500 }}>
        {v}
      </span>
    </div>
  );
}

function FakeFinding({
  icon: Icon, dept, severity, section, text,
}: {
  icon: React.ElementType;
  dept: string;
  severity: "critical" | "high" | "medium" | "low";
  section: string;
  text: string;
}) {
  const sevColor = severity === "critical" ? "#ef4444" : severity === "high" ? "#f59e0b" : "#64748b";
  return (
    <div className="px-4 py-3 flex items-start gap-3">
      <div className="mt-0.5"><Icon className="w-4 h-4" style={{ color: sevColor }} /></div>
      <div className="flex-1 min-w-0">
        <div className="flex flex-wrap items-baseline gap-2 mb-0.5">
          <span className="text-xs font-mono font-semibold" style={{ color: "var(--accent-bright)" }}>
            {section}
          </span>
          <span className="text-[10px] uppercase tracking-wide font-medium" style={{ color: sevColor }}>
            {severity}
          </span>
          <span className="text-[10px]" style={{ color: "var(--text-muted)" }}>· {dept}</span>
        </div>
        <p className="text-xs leading-relaxed" style={{ color: "var(--text-secondary)" }}>{text}</p>
      </div>
    </div>
  );
}

// ─────────────────────── How it works ───────────────────────

function HowItWorks() {
  const steps = [
    { n: 1, title: "Upload your plan set",
      body: "Drag in a PDF — anything from a 5-sheet ADU set to a full commercial submittal." },
    { n: 2, title: "12 agents review in parallel",
      body: "Surveyor identifies jurisdiction. 10 department reviewers run in parallel, each grounded in verbatim code text. ~90 seconds." },
    { n: 3, title: "Get a structured report",
      body: "Compliant / Non-compliant / Needs review per finding. Cited section. Concrete recommendation. Sharable with your team or inspector — free for them." },
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
            Three steps. No subscription.
          </h2>
        </div>
        <div className="grid md:grid-cols-3 gap-5">
          {steps.map((s) => (
            <div key={s.n} className="p-6 rounded-xl"
                 style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}>
              <div className="text-xs font-mono mb-3" style={{ color: "var(--accent)" }}>
                {String(s.n).padStart(2, "0")}
              </div>
              <h3 className="font-semibold mb-2" style={{ color: "var(--text-primary)" }}>{s.title}</h3>
              <p className="text-sm leading-relaxed" style={{ color: "var(--text-secondary)" }}>{s.body}</p>
            </div>
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
          {agents.map(({ Icon, name }) => (
            <div key={name}
                 className="flex flex-col items-center justify-center text-center p-4 rounded-xl"
                 style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}>
              <Icon className="w-5 h-5 mb-2" style={{ color: "var(--accent-bright)" }} />
              <div className="text-xs font-medium" style={{ color: "var(--text-primary)" }}>{name}</div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

// ─────────────────────── Pricing ───────────────────────

function Pricing() {
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
            Pay per check. No subscription.
          </h2>
          <p className="text-base max-w-xl mx-auto" style={{ color: "var(--text-secondary)" }}>
            One credit = one full plan review. Credits never expire. First check is free.
          </p>
        </div>

        <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-4">
          {PRICING.map((p) => (
            <div
              key={p.credits}
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
              </div>
              <div className="text-xs mb-4" style={{ color: "var(--text-secondary)" }}>
                {p.credits === 1
                  ? "1 check"
                  : `${p.credits} checks · $${p.per.toFixed(2)} each`}
              </div>
              <Link
                href="/signup?redirect=/dashboard"
                className="mt-auto text-center text-sm font-medium py-2 rounded-lg"
                style={{
                  background: p.highlight ? "#0B0E14" : "var(--bg-elevated)",
                  color: p.highlight ? "#fff" : "var(--text-primary)",
                  border: p.highlight ? "none" : "1px solid var(--border)",
                }}
              >
                Get started
              </Link>
            </div>
          ))}
        </div>

        <div className="text-center mt-6 text-xs" style={{ color: "var(--text-muted)" }}>
          Inviting contractors and inspectors to view a report is free — they don&apos;t need a Up2Code account.
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
          Run your first check — free
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
