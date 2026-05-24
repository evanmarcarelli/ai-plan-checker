"use client";

import { useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { ChevronLeft, Loader2 } from "lucide-react";
import {
  getMe, createPackCheckoutSession, type UserProfile, type PackSize,
} from "@/lib/api";

// Pay-per-use credit packs — single source of truth here, mirrors the
// PRICING table on the marketing landing page. Change endpoints in BOTH
// places together (or factor into a shared module if this gets edited often).
// Endpoints: 1 = $60, 100 = $2,999. Middle tiers linearly interpolated.
interface Pack {
  size: PackSize;
  price: number;
  per: number;
  label: string;
  tagline: string;
  highlight?: boolean;
}

const PACKS: Pack[] = [
  { size: 1,   price:   60, per: 60.00, label: "Try one",
    tagline: "A single plan check to evaluate the product." },
  { size: 5,   price:  179, per: 35.80, label: "Single project",
    tagline: "Cover one project end-to-end with revisions." },
  { size: 25,  price:  772, per: 30.88, label: "Firm pack", highlight: true,
    tagline: "For active firms with steady submittal volume." },
  { size: 100, price: 2999, per: 29.99, label: "Annual / enterprise",
    tagline: "Annual allotment for high-volume firms." },
];


export default function BillingPage() {
  const router = useRouter();
  const search = useSearchParams();
  const [profile, setProfile] = useState<UserProfile | null>(null);
  const [busyPack, setBusyPack] = useState<PackSize | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getMe().then(setProfile).catch(() => setProfile(null));
  }, []);

  // Auto-resume checkout flow when arriving via /signup?redirect=/billing?pack=N
  // (i.e. the marketing-page → sign-up → here path).
  useEffect(() => {
    const raw = search.get("pack");
    if (!raw) return;
    const n = Number(raw);
    const valid: PackSize[] = [1, 5, 25, 100];
    if (!valid.includes(n as PackSize)) return;
    void buyPack(n as PackSize);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search]);

  async function buyPack(pack: PackSize) {
    setBusyPack(pack);
    setError(null);
    try {
      const { url } = await createPackCheckoutSession(pack);
      window.location.href = url;
    } catch (e) {
      setError(e instanceof Error ? e.message : "Checkout failed");
      setBusyPack(null);
    }
  }

  return (
    <div className="min-h-screen px-6 py-12" style={{ background: "var(--bg)" }}>
      <div className="max-w-6xl mx-auto">
        <button
          onClick={() => router.push("/dashboard")}
          className="inline-flex items-center gap-1.5 text-sm mb-8 hover:underline"
          style={{ color: "var(--text-secondary)" }}
        >
          <ChevronLeft className="w-4 h-4" />
          Back to dashboard
        </button>

        <div className="text-center mb-12">
          <h1 className="text-4xl font-bold mb-3"
              style={{ color: "var(--text-primary)", fontFamily: "var(--font-display)" }}>
            Buy credits
          </h1>
          <p className="text-base" style={{ color: "var(--text-secondary)" }}>
            One credit = one full plan review. Credits never expire. No subscription.
          </p>
          {profile && profile.credits_remaining !== undefined && (
            <div className="mt-4 inline-flex items-center gap-2 px-3 py-1.5 rounded-full text-xs"
                 style={{ background: "var(--bg-card)", border: "1px solid var(--border)", color: "var(--text-secondary)" }}>
              Current balance:&nbsp;
              <strong style={{ color: "var(--text-primary)" }}>
                {profile.credits_remaining} {profile.credits_remaining === 1 ? "credit" : "credits"}
              </strong>
            </div>
          )}
        </div>

        {error && (
          <div className="max-w-md mx-auto mb-6 px-4 py-3 rounded-lg text-sm"
               style={{ background: "var(--non-compliant-bg)", color: "var(--non-compliant)" }}>
            {error}
          </div>
        )}

        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          {PACKS.map((p) => {
            const isLoading = busyPack === p.size;
            return (
              <div
                key={p.size}
                className="rounded-2xl p-5 relative flex flex-col"
                style={{
                  background: "var(--bg-card)",
                  border: p.highlight ? "2px solid var(--accent-bright)" : "1px solid var(--border)",
                }}
              >
                {p.highlight && (
                  <div className="absolute -top-3 left-1/2 -translate-x-1/2 text-[10px] font-bold uppercase tracking-widest px-3 py-1 rounded-full"
                       style={{ background: "#0B0E14", color: "#fff" }}>
                    Most popular
                  </div>
                )}
                <div className="text-xs uppercase tracking-wide" style={{ color: "var(--text-muted)" }}>
                  {p.label}
                </div>
                <div className="mt-2 mb-1 flex items-baseline gap-1">
                  <span className="text-3xl font-bold"
                        style={{ fontFamily: "var(--font-display)", color: "var(--text-primary)" }}>
                    ${p.price.toLocaleString()}
                  </span>
                </div>
                <div className="text-xs mb-3" style={{ color: "var(--text-secondary)" }}>
                  {p.size === 1
                    ? "1 check"
                    : `${p.size} checks · $${p.per.toFixed(2)} each`}
                </div>
                <p className="text-xs mb-5 leading-relaxed flex-1" style={{ color: "var(--text-muted)" }}>
                  {p.tagline}
                </p>

                <button
                  onClick={() => void buyPack(p.size)}
                  disabled={busyPack !== null}
                  className="w-full py-2.5 rounded-lg font-medium text-sm disabled:opacity-60 flex items-center justify-center gap-2"
                  style={{
                    background: p.highlight ? "#0B0E14" : "var(--bg-elevated)",
                    color: p.highlight ? "#fff" : "var(--text-primary)",
                    border: p.highlight ? "none" : "1px solid var(--border)",
                  }}
                >
                  {isLoading && <Loader2 className="w-4 h-4 animate-spin" />}
                  {isLoading ? "Redirecting…" : `Buy ${p.size} ${p.size === 1 ? "credit" : "credits"}`}
                </button>
              </div>
            );
          })}
        </div>

        <p className="text-center text-xs mt-10" style={{ color: "var(--text-muted)" }}>
          Payments are processed securely by Stripe. You&apos;ll be redirected to Stripe Checkout.
        </p>
      </div>
    </div>
  );
}
