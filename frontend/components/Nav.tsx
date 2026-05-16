"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
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
    <nav className="bg-white border-b border-slate-200 px-6 py-3 flex items-center justify-between">
      <Link href="/dashboard" className="font-bold text-slate-900">
        AI Plan Checker
      </Link>
      <div className="flex items-center gap-4 text-sm">
        {profile && (
          <>
            <span className="text-slate-500">
              {profile.firm_name || profile.email}
            </span>
            <span className="bg-amber-50/10 text-amber-300 border border-amber-300/30 px-2 py-1 rounded font-medium">
              {profile.credits_remaining} {profile.credits_remaining === 1 ? "credit" : "credits"}
            </span>
            <button
              onClick={signOut}
              className="text-slate-500 hover:text-slate-700 font-medium"
            >
              Sign out
            </button>
          </>
        )}
      </div>
    </nav>
  );
}
