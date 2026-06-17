-- ============================================================
-- Migration 013: Supabase Security Advisor hardening
--
-- WHY THIS EXISTS
-- The Supabase Security Advisor flagged six lints on the production
-- project (ai-plan-checker). Five are addressed here; the sixth
-- (leaked-password protection) is an Auth/GoTrue dashboard toggle, not
-- a database object, and is gated behind the Pro plan -- see the note
-- at the bottom. This migration was applied to the live DB on
-- 2026-06-16 (migration `harden_function_security_advisors`); this file
-- mirrors it so the repo and the remote stay in sync.
--
-- WHAT IT FIXES
--  1. function_search_path_mutable on public.set_updated_at
--     The trigger fn (migration 001) had no pinned search_path. Its body
--     only calls now() (pg_catalog, always resolvable), so pinning an
--     empty search_path is safe and closes the resolution-hijack vector.
--     Matches the search_path discipline established in migrations 006/007.
--
--  2/4. handle_new_user() (migration 001) is a SECURITY DEFINER trigger
--     on auth.users. It must never be reachable via PostgREST RPC by the
--     anon/authenticated roles. Triggers fire WITHOUT an EXECUTE privilege
--     check, so revoking these grants does NOT break the signup ->
--     public.profiles insert.
--
--  3/5. rls_auto_enable() is a SECURITY DEFINER *event trigger* (fires on
--     DDL). Event triggers also fire without an EXECUTE check, so revoking
--     RPC access from anon/authenticated is safe.
--
-- service_role keeps its grant (the trusted backend role); only the
-- public/anon/authenticated grants are removed, which is exactly what the
-- advisor lints 0028/0029 ask for.
-- ============================================================

-- 1. Pin search_path on the updated_at trigger fn (lint 0011)
alter function public.set_updated_at() set search_path = '';

-- 2 & 4. Remove RPC exposure of the signup trigger fn (lints 0028/0029)
revoke execute on function public.handle_new_user() from public;
revoke execute on function public.handle_new_user() from anon;
revoke execute on function public.handle_new_user() from authenticated;

-- 3 & 5. Remove RPC exposure of the RLS auto-enable event-trigger fn
revoke execute on function public.rls_auto_enable() from public;
revoke execute on function public.rls_auto_enable() from anon;
revoke execute on function public.rls_auto_enable() from authenticated;

-- ------------------------------------------------------------
-- NOT HANDLED HERE (no SQL surface):
--   6. auth_leaked_password_protection -- "Prevent use of leaked passwords"
--      (HaveIBeenPwned check). This is a GoTrue Auth setting under
--      Dashboard > Authentication > Attack Protection, and is "Only
--      available on Pro plan and above". The project is on the Free plan,
--      so it cannot be enabled without a paid upgrade. Free-tier baseline
--      already in place: min password length 10 + lower/upper/digit/symbol
--      requirement. Enable the HIBP toggle after any upgrade to Pro.
-- ------------------------------------------------------------
