"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Check, ChevronLeft, Loader2 } from "lucide-react";
import { getMe, createCheckoutSession, createPortalSession, type UserProfile } from "@/lib/api";

interface Plan {
  id: "starter" | "professional" | "unlimited";
  name: string;
  price: number;
  credits: string;
  tagline: string;
  features: string[];
  recommended?: boolean;
}

const PLANS: Plan[] = [
  {
    id: "starter",
    name: "Starter",
    price: 49,
    credits: "10 reviews / month",
    tagline: "For solo architects and small firms",
    features: [
      "10 full multi-department reviews each month",
      "All 12 AI agents (Surveyor, Librarian, 10 departments)",
      "PDF export of every report",
      "Email support",
    ],
  },
  {
    id: "professional",
    name: "Professional",
    price: 149,
    credits: "50 reviews / month",
    tagline: "For active firms with consistent submittal volume",
    features: [
      "50 full multi-department reviews each month",
      "All 12 AI agents",
      "PDF + CSV export",
      "Priority email support",
      "Save and revisit historical reports",
    ],
    recommended: true,
  },
  {
    id: "unlimited",
    name: "Unlimited",
    price: 399,
    credits: "Unlimited reviews",
    tagline: "For high-volume firms and AHJs",
    features: [
      "Unlimited reviews",
      "All 12 AI agents",
      "PDF + CSV export",
      "Priority support + onboarding call",
      "Team seats (coming soon)",
    ],
  },
];

export default function BillingPage() {
  const router = useRouter();
  const [profile, setProfile] = useState<UserProfile | null>(null);
  const [loading, setLoading] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getMe().then(setProfile).catch(() => setProfile(null));
  }, []);

  const currentTier = profile?.plan_tier || "free";

  async function handleSubscribe(plan: "starter" | "professional" | "unlimited") {
    setLoading(plan);
    setError(null);
    try {
      const { url } = await createCheckoutSession(plan);
      window.location.href = url;
    } catch (e) {
      setError(e instanceof Error ? e.message : "Checkout failed");
      setLoading(null);
    }
  }

  async function handleManage() {
    setLoading("portal");
    setError(null);
    try {
      const { url } = await createPortalSession();
      window.location.href = url;
    } catch (e) {
      setError(e instanceof Error ? e.message : "Portal failed");
      setLoading(null);
    }
  }

  return (
    <div className="min-h-screen px-6 py-12" style={{ background: "var(--bg)" }}>
      <div className="max-w-6xl mx-auto">
        {/* Back link */}
        <button
          onClick={() => router.push("/dashboard")}
          className="inline-flex items-center gap-1.5 text-sm mb-8 hover:underline"
          style={{ color: "var(--text-secondary)" }}
        >
          <ChevronLeft className="w-4 h-4" />
          Back to dashboard
        </button>

        {/* Header */}
        <div className="text-center mb-12">
          <h1 className="text-4xl font-bold mb-3"
              style={{ color: "var(--text-primary)", fontFamily: "var(--font-display)" }}>
            Choose your plan
          </h1>
          <p className="text-base" style={{ color: "var(--text-secondary)" }}>
            Cancel any time. Test mode — no real charges yet.
          </p>
          {profile && (
            <div className="mt-4 inline-flex items-center gap-2 px-3 py-1.5 rounded-full text-xs"
                 style={{ background: "var(--bg-card)", border: "1px solid var(--border)", color: "var(--text-secondary)" }}>
              Current plan: <strong style={{ color: "var(--text-primary)" }}>
                {currentTier.charAt(0).toUpperCase() + currentTier.slice(1)}
              </strong>
              {profile.credits_remaining !== undefined && (
                <span style={{ color: "var(--text-muted)" }}>
                  · {profile.credits_remaining} credits remaining
                </span>
              )}
            </div>
          )}
        </div>

        {error && (
          <div className="max-w-md mx-auto mb-6 px-4 py-3 rounded-lg text-sm"
               style={{ background: "var(--non-compliant-bg)", color: "var(--non-compliant)" }}>
            {error}
          </div>
        )}

        {/* Plan grid */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {PLANS.map((plan) => {
            const isCurrent = currentTier === plan.id;
            const isLoading = loading === plan.id;
            return (
              <div
                key={plan.id}
                className="rounded-2xl p-6 relative flex flex-col"
                style={{
                  background: "var(--bg-card)",
                  border: plan.recommended
                    ? "1px solid var(--border-bright)"
                    : "1px solid var(--border)",
                  boxShadow: plan.recommended ? "0 0 0 1px var(--accent-glow)" : undefined,
                }}
              >
                {plan.recommended && (
                  <div className="absolute -top-3 left-1/2 -translate-x-1/2 text-xs px-3 py-1 rounded-full font-medium"
                       style={{
                         background: "#0B0E14",
                         color: "#fff",
                       }}>
                    Most popular
                  </div>
                )}
                <div className="mb-1 text-sm font-semibold"
                     style={{ color: "var(--accent-bright)", fontFamily: "var(--font-display)" }}>
                  {plan.name}
                </div>
                <div className="mb-4 text-xs" style={{ color: "var(--text-muted)" }}>
                  {plan.tagline}
                </div>
                <div className="mb-1 flex items-baseline gap-1">
                  <span className="text-4xl font-bold" style={{ color: "var(--text-primary)", fontFamily: "var(--font-display)" }}>
                    ${plan.price}
                  </span>
                  <span className="text-sm" style={{ color: "var(--text-muted)" }}>/ month</span>
                </div>
                <div className="mb-6 text-sm font-medium" style={{ color: "var(--text-secondary)" }}>
                  {plan.credits}
                </div>

                <ul className="space-y-2.5 mb-8 flex-1">
                  {plan.features.map((f) => (
                    <li key={f} className="flex items-start gap-2 text-sm" style={{ color: "var(--text-secondary)" }}>
                      <Check className="w-4 h-4 flex-shrink-0 mt-0.5" style={{ color: "var(--compliant)" }} />
                      <span>{f}</span>
                    </li>
                  ))}
                </ul>

                <button
                  onClick={() => (isCurrent ? handleManage() : handleSubscribe(plan.id))}
                  disabled={isLoading || loading === "portal"}
                  className="w-full py-2.5 rounded-lg font-medium text-sm transition-all disabled:opacity-60 flex items-center justify-center gap-2"
                  style={
                    isCurrent
                      ? {
                          background: "var(--bg-elevated)",
                          color: "var(--text-primary)",
                          border: "1px solid var(--border)",
                        }
                      : plan.recommended
                      ? {
                          background: "#0B0E14",
                          color: "#fff",
                        }
                      : {
                          background: "var(--bg-elevated)",
                          color: "var(--text-primary)",
                          border: "1px solid var(--border)",
                        }
                  }
                >
                  {isLoading && <Loader2 className="w-4 h-4 animate-spin" />}
                  {isCurrent ? "Manage subscription" : `Subscribe to ${plan.name}`}
                </button>
              </div>
            );
          })}
        </div>

        <p className="text-center text-xs mt-10" style={{ color: "var(--text-muted)" }}>
          Use Stripe test card <code>4242 4242 4242 4242</code> · any future date · any CVC.
        </p>
      </div>
    </div>
  );
}
