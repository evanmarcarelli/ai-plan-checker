-- ============================================================
-- Migration 004: public feedback board
--
-- Anyone signed in can post a request or report. Anyone signed in can
-- upvote (one vote per user per post, enforced by the composite PK).
-- The board is intentionally public-readable so the founder and visitors
-- can see what's being asked for. Status field lets the founder mark
-- "shipped" / "considering" / "wontfix" without deleting posts.
-- ============================================================

create table if not exists public.feedback_posts (
  id uuid primary key default gen_random_uuid(),
  author_user_id uuid not null references auth.users(id) on delete cascade,
  author_display text not null,
  title text not null,
  body text not null default '',
  status text not null default 'open',     -- open|considering|planned|shipped|wontfix
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

create index if not exists feedback_posts_created_idx on public.feedback_posts (created_at desc);
create index if not exists feedback_posts_status_idx on public.feedback_posts (status);

create table if not exists public.feedback_votes (
  post_id uuid not null references public.feedback_posts(id) on delete cascade,
  voter_user_id uuid not null references auth.users(id) on delete cascade,
  created_at timestamptz default now(),
  primary key (post_id, voter_user_id)      -- 1 vote per user per post
);

create index if not exists feedback_votes_post_idx on public.feedback_votes (post_id);

-- RLS: anyone signed in can read everything (it's a public board).
-- Writes go through the backend service role.
alter table public.feedback_posts enable row level security;
alter table public.feedback_votes enable row level security;

create policy "Anyone signed-in can read posts"
  on public.feedback_posts for select
  using (auth.role() = 'authenticated');

create policy "Anyone signed-in can read votes"
  on public.feedback_votes for select
  using (auth.role() = 'authenticated');

-- Updated_at trigger
create trigger feedback_posts_set_updated_at before update on public.feedback_posts
  for each row execute function public.set_updated_at();
