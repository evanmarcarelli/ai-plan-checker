-- ============================================================
-- Migration 009: provision-tree ancestor expansion
--
-- The provisions table (migration 008) holds the structural code tree
-- (chapter -> section -> subsection), populated by
-- scripts/ingest/build_provisions.py. This RPC returns a node plus all its
-- ancestors so context assembly can attach the inherited scope to a finding
-- ("§1004.1.1 is inside Chapter 10, Means of Egress").
--
-- ltree ancestor queries (path @>) need a function — PostgREST can't express
-- the @> operator through the query builder. SECURITY DEFINER + pinned
-- search_path, matching the other migrations.
-- ============================================================

create or replace function public.get_provision_ancestors(
  p_edition_id text,
  p_path       ltree
)
returns table (path text, number text, kind text, heading text,
               text text, depth int)
language sql
security definer
set search_path = public
as $$
  select p.path::text, p.number, p.kind, p.heading, p.text, nlevel(p.path) depth
  from provisions p
  where p.edition_id = p_edition_id
    and p.path @> p_path          -- ancestors-or-self of p_path
  order by nlevel(p.path);
$$;
