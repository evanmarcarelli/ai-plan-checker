"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { ArrowUpRight } from "lucide-react";
import { createClient } from "@/lib/supabase/client";
import { getMe, type UserProfile } from "@/lib/api";

export default function Nav() {
  const router = useRouter();
  const [profile, setProfile] = useState<UserProfile | null>(null);

  useEffect(() => {
    getMe().then(setProfile).catch(() => setProfile(null));
  }, []);

  async function signOut() {
    const supabase = createClient();
    await supabase.auth.signOut();
    router.push("/login");
    router.refresh();
  }

  return (
    <nav
      className="border-b px-6 py-3 flex items-center justify-between"
      style={{ background: "var(--bg-card)", borderColor: "var(--border)" }}
    >
      <Link href="/dashboard" className="flex items-center gap-1" aria-label="Architechtura home">
        {/* Wordmark — "Architechtura" followed by the northeast arrow */}
        <span
          className="font-semibold text-[15px] tracking-tight"
          style={{ color: "var(--text-primary)" }}
        >
          Architechtura
        </span>
        <ArrowUpRight
          className="w-3.5 h-3.5"
          strokeWidth={2.5}
          style={{ color: "var(--text-primary)" }}
        />
      </Link>
      <div className="flex items-center gap-4 text-sm">
        {profile && (
          <>
            <span style={{ color: "var(--text-secondary)" }}>
              {profile.firm_name || profile.email}
            </span>
            <span
              className="px-2 py-1 rounded font-medium"
              style={{
                background: "var(--accent-glow)",
                color: "var(--accent)",
                border: "1px solid rgba(184, 148, 31, 0.25)",
              }}
            >
              {profile.credits_remaining} {profile.credits_remaining === 1 ? "credit" : "credits"}
            </span>
            <button
              onClick={signOut}
              className="font-medium"
              style={{ color: "var(--text-secondary)" }}
            >
              Sign out
            </button>
          </>
        )}
      </div>
    </nav>
  );
}
