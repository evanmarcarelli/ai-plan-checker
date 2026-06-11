"""Plan-set library: the durable, searchable corpus of uploaded plan sets.

Persistence side of migration 010. After a job's pipeline completes, the
worker calls persist_plan_document() to write the extracted plan set into
plan_documents + plan_sheets, so that:

  * a re-upload of the same bytes is detected (file_hash dedupe) and linked
    instead of duplicated;
  * a new revision of the same project (same address / permit number,
    different hash) is chained via revision_of;
  * every sheet's text is FTS-indexed for cross-plan retrieval by agents
    and humans ("which sheets mention Type V-B?", "show me the structural
    sheets for this address").

Every entry point here is BEST-EFFORT: a missing migration, a Supabase
hiccup, or a malformed sheet must never fail the job that produced a
perfectly good report. Failures are logged and swallowed.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.models.schemas import ExtractedPlanData
from app.services import db
from app.utils.logger import get_logger

logger = get_logger(__name__)

# Sheets are inserted in batches to stay under PostgREST payload limits.
_SHEET_BATCH = 50

# Sheet text is capped per row. FTS quality degrades little and the table
# stays lean; the full text remains in jobs.plan_data for the source job.
_MAX_SHEET_CHARS = 20_000


def find_existing_by_hash(user_id: str, file_hash: str) -> Optional[Dict[str, Any]]:
    """Return the user's existing plan_documents row for this file hash."""
    if not (user_id and file_hash):
        return None
    try:
        res = (
            db.admin().table("plan_documents")
            .select("id, filename, created_at, source_job_id, revision_of")
            .eq("user_id", user_id)
            .eq("file_hash", file_hash)
            .limit(1)
            .execute()
        )
        return res.data[0] if res.data else None
    except Exception as e:
        logger.warning(f"[plan_library] hash lookup failed (migration 010 applied?): {e}")
        return None


def _find_revision_predecessor(
    user_id: str,
    address: Optional[str],
    permit: Optional[str],
    exclude_hash: str,
) -> Optional[str]:
    """Most recent prior document that looks like the same project."""
    if not (address or permit):
        return None
    try:
        res = db.admin().rpc(
            "find_plan_revision_candidates",
            {
                "p_user_id": user_id,
                "p_address": address or "",
                "p_permit": permit or "",
                "p_exclude_hash": exclude_hash,
            },
        ).execute()
        rows = res.data or []
        return rows[0]["id"] if rows else None
    except Exception as e:
        logger.warning(f"[plan_library] revision lookup failed: {e}")
        return None


def _sheet_rows(
    plan_document_id: str,
    user_id: str,
    plan_data: ExtractedPlanData,
) -> List[Dict[str, Any]]:
    """Build plan_sheets rows from the extraction output.

    One row per page in raw_text_by_page, enriched with the sheet_index
    record for that page; plus index-only records (sheets the cover index
    lists but no page matched) so set completeness is queryable.
    """
    by_page: Dict[int, Dict[str, Any]] = {}
    index_only: List[Dict[str, Any]] = []
    for rec in plan_data.sheet_index or []:
        pn = rec.get("page_number")
        if pn is not None:
            by_page[int(pn)] = rec
        elif rec.get("sheet_number"):
            index_only.append(rec)

    rows: List[Dict[str, Any]] = []
    for page_num, text in sorted((plan_data.raw_text_by_page or {}).items()):
        rec = by_page.get(int(page_num), {})
        body = (text or "")[:_MAX_SHEET_CHARS]
        rows.append({
            "plan_document_id": plan_document_id,
            "user_id": user_id,
            "page_number": int(page_num),
            "sheet_number": rec.get("sheet_number"),
            "sheet_title": rec.get("sheet_title"),
            "discipline": rec.get("discipline"),
            "category": rec.get("category"),
            "source": rec.get("source"),
            "confidence": float(rec.get("confidence") or 0.0),
            "used_ocr": "--- OCR (Textract) ---" in (text or ""),
            "char_count": len(text or ""),
            "text": body,
        })
    for rec in index_only:
        rows.append({
            "plan_document_id": plan_document_id,
            "user_id": user_id,
            "page_number": None,
            "sheet_number": rec.get("sheet_number"),
            "sheet_title": rec.get("sheet_title"),
            "discipline": rec.get("discipline"),
            "category": rec.get("category"),
            "source": "index_only",
            "confidence": float(rec.get("confidence") or 0.0),
            "used_ocr": False,
            "char_count": 0,
            "text": None,
        })
    return rows


def persist_plan_document(
    job_id: str,
    user_id: str,
    plan_data: Optional[ExtractedPlanData],
) -> Optional[str]:
    """Persist a completed job's plan set into the library.

    Returns the plan_documents id (existing or new), or None when nothing
    could be persisted. Never raises.
    """
    if plan_data is None or not user_id:
        return None
    file_hash = plan_data.file_hash
    if not file_hash:
        logger.info(f"[plan_library] job {job_id}: no file_hash on plan_data; skipping")
        return None

    try:
        # 1. Dedupe: same bytes already in the library → just link the job.
        existing = find_existing_by_hash(user_id, file_hash)
        if existing:
            logger.info(
                f"[plan_library] job {job_id}: duplicate of plan_document "
                f"{existing['id']} (uploaded {existing.get('created_at')}); linking."
            )
            _link_job(job_id, file_hash, existing["id"])
            return existing["id"]

        # 2. Revision chain: same project, different bytes.
        revision_of = _find_revision_predecessor(
            user_id, plan_data.project_address, None, file_hash
        )

        # 3. Insert the document row.
        doc = {
            "user_id": user_id,
            "file_hash": file_hash,
            "source_job_id": job_id,
            "page_count": plan_data.page_count,
            "project_name": plan_data.project_name,
            "project_address": plan_data.project_address,
            "occupancy_type": plan_data.occupancy_type,
            "construction_type": plan_data.construction_type,
            "plan_type": plan_data.plan_type.value if plan_data.plan_type else None,
            "revision_of": revision_of,
            "extraction_stats": plan_data.extraction_stats or None,
        }
        res = db.admin().table("plan_documents").insert(doc).execute()
        plan_document_id = res.data[0]["id"]

        # 4. Insert the sheets in batches.
        rows = _sheet_rows(plan_document_id, user_id, plan_data)
        for i in range(0, len(rows), _SHEET_BATCH):
            db.admin().table("plan_sheets").insert(rows[i:i + _SHEET_BATCH]).execute()

        # 5. Link the job.
        _link_job(job_id, file_hash, plan_document_id)

        logger.info(
            f"[plan_library] job {job_id}: persisted plan_document {plan_document_id} "
            f"({len(rows)} sheet rows"
            + (f", revision of {revision_of}" if revision_of else "")
            + ")"
        )
        return plan_document_id

    except Exception as e:
        logger.warning(
            f"[plan_library] job {job_id}: persistence skipped "
            f"(apply migration 010 for the plan library): {e}"
        )
        return None


def _link_job(job_id: str, file_hash: str, plan_document_id: str) -> None:
    """Backfill the job row with its corpus linkage. Backward-compatible:
    pre-migration deployments simply skip the columns."""
    try:
        db.update_job(job_id, {
            "file_hash": file_hash,
            "plan_document_id": plan_document_id,
        })
    except Exception:
        try:
            db.update_job(job_id, {"file_hash": file_hash})
        except Exception:
            pass


def search_sheets(
    user_id: str,
    query: str,
    *,
    disciplines: Optional[List[str]] = None,
    document_id: Optional[str] = None,
    limit: int = 20,
) -> List[Dict[str, Any]]:
    """Ranked FTS search over the user's plan corpus. [] on any failure."""
    if not (user_id and query and query.strip()):
        return []
    try:
        res = db.admin().rpc("search_plan_sheets", {
            "p_user_id": user_id,
            "p_query": query.strip(),
            "p_disciplines": disciplines,
            "p_document_id": document_id,
            "p_limit": max(1, min(int(limit), 100)),
        }).execute()
        return res.data or []
    except Exception as e:
        logger.warning(f"[plan_library] search failed: {e}")
        return []


def list_documents(user_id: str, limit: int = 50) -> List[Dict[str, Any]]:
    """The user's plan library, newest first. [] on any failure."""
    try:
        res = (
            db.admin().table("plan_documents")
            .select("id, filename, project_name, project_address, page_count, "
                    "occupancy_type, construction_type, plan_type, revision_of, "
                    "source_job_id, created_at")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        return res.data or []
    except Exception as e:
        logger.warning(f"[plan_library] list failed: {e}")
        return []
