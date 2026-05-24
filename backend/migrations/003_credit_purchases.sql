-- ============================================================
-- Migration 003: credit_purchases
--
-- Append-only log of every successful credit-pack purchase. The
-- UNIQUE(stripe_session_id) constraint is the idempotency anchor for the
-- Stripe webhook — if Stripe re-fires checkout.session.completed (which
-- it routinely does on transient failures), the second insert collides
-- and the webhook skips the credit grant.
--
-- Also serves as the audit log for support / accounting / refunds.
-- ============================================================

create table if not exists public.credit_purchases (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  stripe_session_id text not null unique,    -- the idempotency key
  pack_size integer not null,                -- 1 | 5 | 25 | 100
  credits_added integer not null,
  amount_cents integer not null default 0,   -- gross paid, in cents
  currency text not null default 'usd',
  created_at timestamptz default now()
);

create index if not exists credit_purchases_user_id_idx on public.credit_purchases (user_id, created_at desc);
create index if not exists credit_purchases_session_id_idx on public.credit_purchases (stripe_session_id);

-- RLS: owners can read their own purchase history; all writes go through
-- the backend service role (the webhook), so no insert policy.
alter table public.credit_purchases enable row level security;

create policy "Users can read own credit purchases"
  on public.credit_purchases for select
  using (auth.uid() = user_id);
