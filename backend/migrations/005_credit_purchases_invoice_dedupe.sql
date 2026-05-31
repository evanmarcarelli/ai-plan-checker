-- ============================================================
-- Migration 005: credit_purchases invoice-based dedupe
--
-- The pack-pricing tiers became recurring subscriptions, so the
-- idempotency key for credit grants shifts from Stripe's checkout
-- session ID to the invoice ID (one per billing cycle).
--
-- - Adds `stripe_invoice_id` with its own UNIQUE constraint.
-- - Relaxes `stripe_session_id` to nullable so subscription-renewal
--   rows (which only carry invoice_id) can be inserted.
-- ============================================================

alter table public.credit_purchases
  alter column stripe_session_id drop not null;

alter table public.credit_purchases
  add column if not exists stripe_invoice_id text unique;

create index if not exists credit_purchases_invoice_id_idx
  on public.credit_purchases (stripe_invoice_id);
