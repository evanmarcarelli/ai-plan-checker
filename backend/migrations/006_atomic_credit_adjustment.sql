-- ============================================================
-- Migration 006: atomic credit adjustment
--
-- The previous decrement_credits()/add_credits() helpers did a
-- read-modify-write in Python (SELECT balance, check, then UPDATE).
-- Two uploads landing in the same instant both read balance=1, both
-- pass the check, and both run — one credit, two reviews. These two
-- functions move the decision into a single atomic UPDATE so the
-- database, not application code, enforces the invariant.
--
-- decrement: only succeeds when the balance covers the amount; the
--   WHERE clause makes the guard and the write one statement. Returns
--   the new balance, or no row (NULL) when insufficient/ missing.
-- increment: unconditional add (used for refunds + pack grants).
--
-- Both are SECURITY DEFINER with a pinned search_path. The backend
-- calls them with the service-role key (which already bypasses RLS),
-- but pinning search_path avoids any function-resolution hijack.
-- ============================================================

create or replace function public.decrement_credits_atomic(
  p_user_id uuid,
  p_amount  integer default 1
)
returns integer
language sql
security definer
set search_path = public
as $$
  update public.profiles
     set credits_remaining = credits_remaining - p_amount
   where id = p_user_id
     and credits_remaining >= p_amount
  returning credits_remaining;
$$;

create or replace function public.add_credits_atomic(
  p_user_id uuid,
  p_amount  integer
)
returns integer
language sql
security definer
set search_path = public
as $$
  update public.profiles
     set credits_remaining = credits_remaining + p_amount
   where id = p_user_id
  returning credits_remaining;
$$;
