"""Postgres-backed reads for the structured corpus (migration 008).

This is the cutover seam: the in-memory BM25 path (corpus_loader) can be
populated from here instead of disk, and the new hybrid search / ancestor
expansion live here. EVERY function degrades to an empty/false result if the
migration isn't applied or Supabase isn't configured, so importing or calling
this can never crash the app — the disk path keeps working.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.utils.logger import get_logger

logger = get_logger(__name__)


def _admin():
    """Lazy Supabase service client. Returns None if unavailable so callers
    can fall back to disk instead of raising at import time."""
    try:
        from app.services import db
        return db.admin()
    except Exception as e:
        logger.warning(f"[code_store] Supabase client unavailable: {e}")
        return None


def corpus_in_postgres() -> bool:
    """True iff code_chunks exists and has at least one row."""
    client = _admin()
    if client is None:
        return False
    try:
        res = client.table("code_chunks").select("chunk_id").limit(1).execute()
        return bool(res.data)
    except Exception as e:
        logger.info(f"[code_store] code_chunks not queryable yet (migration 008?): {e}")
        return False


def fetch_all_chunks(batch: int = 1000) -> List[Dict[str, Any]]:
    """Page through every code_chunks row. Used to build the in-memory
    CodeCorpus from Postgres (so BM25 keeps working, data lives in the DB)."""
    client = _admin()
    if client is None:
        return []
    rows: List[Dict[str, Any]] = []
    start = 0
    try:
        while True:
            res = (client.table("code_chunks")
                   .select("chunk_id, adoption_id, code_short, version, section, "
                           "path, parent_section, citation, discipline, heading, "
                           "context_header, body, jurisdictions, tags, source_tier, "
                           "license_status")
                   .range(start, start + batch - 1)
                   .execute())
            page = res.data or []
            rows.extend(page)
            if len(page) < batch:
                break
            start += batch
    except Exception as e:
        logger.warning(f"[code_store] fetch_all_chunks failed: {e}")
        return rows
    logger.info(f"[code_store] fetched {len(rows)} chunks from Postgres")
    return rows


def search(
    query: str,
    *,
    adoption_ids: Optional[List[str]] = None,
    disciplines: Optional[List[str]] = None,
    k: int = 20,
    query_embedding: Optional[List[float]] = None,
) -> List[Dict[str, Any]]:
    """Hybrid lexical+vector search via the search_code_chunks RPC. With no
    embedding it's pure FTS (the current state until vectors are populated).
    Always pass adoption_ids in production to prevent cross-jurisdiction hits."""
    client = _admin()
    if client is None:
        return []
    try:
        res = client.rpc("search_code_chunks", {
            "p_query_text": query,
            "p_query_emb": query_embedding,   # None -> pure FTS
            "p_adoption_ids": adoption_ids,
            "p_disciplines": disciplines,
            "p_limit": k,
        }).execute()
        return res.data or []
    except Exception as e:
        logger.warning(f"[code_store] search RPC failed: {e}")
        return []


def fetch_provision(edition_id: str, path: str) -> Optional[Dict[str, Any]]:
    """One provision node (base tree). None if missing/unavailable."""
    client = _admin()
    if client is None:
        return None
    try:
        res = (client.table("provisions").select("*")
               .eq("edition_id", edition_id).eq("path", path).limit(1).execute())
        return (res.data or [None])[0]
    except Exception as e:
        logger.warning(f"[code_store] fetch_provision failed: {e}")
        return None


def fetch_amendments(adoption_id: Optional[str], target_path: str) -> List[Dict[str, Any]]:
    """Amendments an adoption makes to a specific provision path. [] if none."""
    client = _admin()
    if client is None or not adoption_id:
        return []
    try:
        res = (client.table("amendments")
               .select("op, new_text, ordinance_cite, effective_date, needs_review")
               .eq("adoption_id", adoption_id).eq("target_path", target_path).execute())
        return res.data or []
    except Exception as e:
        logger.warning(f"[code_store] fetch_amendments failed: {e}")
        return []


def provision_ancestors(edition_id: str, path: str) -> List[Dict[str, Any]]:
    """Provision node + all ancestors (root->leaf) from the structured tree —
    the breadcrumb for context assembly. [] if the RPC/migration is absent."""
    client = _admin()
    if client is None:
        return []
    try:
        res = client.rpc("get_provision_ancestors", {
            "p_edition_id": edition_id, "p_path": path,
        }).execute()
        return res.data or []
    except Exception as e:
        logger.warning(f"[code_store] provision_ancestors RPC failed: {e}")
        return []


def fetch_table_cells(table_id: str, adoption_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """Return the cells of one reference table. Prefers rows scoped to
    adoption_id (a jurisdiction that amended a cell); falls back to the base
    rows (adoption_id IS NULL) when the adoption has no override. Empty list if
    the table/migration/Supabase isn't there, so the caller uses the hardcoded
    fallback."""
    client = _admin()
    if client is None:
        return []
    try:
        res = (client.table("code_table_cells")
               .select("adoption_id, row_key, col_key, value_num, value_sentinel, unit")
               .eq("table_id", table_id)
               .execute())
        rows = res.data or []
    except Exception as e:
        logger.warning(f"[code_store] fetch_table_cells({table_id}) failed: {e}")
        return []
    scoped = [r for r in rows if adoption_id and r.get("adoption_id") == adoption_id]
    base = [r for r in rows if r.get("adoption_id") is None]
    return scoped or base


def ancestors(adoption_id: Optional[str], path: str) -> List[Dict[str, Any]]:
    """Return a chunk and all its ancestors (root->leaf) for context assembly —
    the structural fix for 'this exception only means something inside Ch 10'."""
    client = _admin()
    if client is None:
        return []
    try:
        res = client.rpc("get_chunk_ancestors", {
            "p_adoption_id": adoption_id,
            "p_path": path,
        }).execute()
        return res.data or []
    except Exception as e:
        logger.warning(f"[code_store] ancestors RPC failed: {e}")
        return []
