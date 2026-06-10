"""AI assistant: per-job Q&A grounded in the RAG corpus + this report's findings.

This is the "ask a quick clarifying question" feature. The architect or a
shared collaborator can ask things like:
  - "What does IBC 1011.5.2 actually require in plain English?"
  - "Why was this finding flagged?"
  - "What's the difference between AFCI and GFCI?"

Key properties:
- Uses Sonnet (cheap model) — these are low-effort clarifications, not
  full plan reviews.
- ALWAYS grounded: every assistant reply pulls relevant chunks from the
  BM25 corpus AND the report's own findings, and quotes verbatim text.
- Cited chunks are returned as `citations` so the UI can show them.
- Persisted in chat_messages so any collaborator can scroll the history.
- Rate limited aggressively per actor.

NOTE: deliberately NO `from __future__ import annotations` here — see the
matching note in collab_routes.py. It breaks request-body model resolution
on the pinned FastAPI 0.109 + Pydantic 2.5.x.
"""
from typing import Any, Dict, List, Optional

import anthropic
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.api.collab_routes import Actor, get_actor
from app.api.routes import limiter
from app.code_library.corpus_loader import CodeChunk, get_retriever, get_corpus
from app.config import settings
from app.services import db
from app.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter()


SYSTEM_PROMPT = """You are Architechtura's AI assistant — a building-code clarification helper.

Your job is to answer clarifying questions from architects, contractors, and
inspectors who are looking at a compliance report. You are NOT performing a
new code review and you are NOT a substitute for a licensed professional or
the AHJ. Always remind users to verify with their AHJ for final determinations.

RULES:
1. Ground every claim in the CODE EXCERPTS provided below. If a question
   asks about a section that isn't in the excerpts, say "I don't have that
   section in my reference — please verify directly with the source."
2. Quote the relevant section in your answer (cite by section number).
3. Be concise: 2-5 sentences for clarification questions, longer only for
   substantive comparisons.
4. If the question is about a specific finding in the report, use the
   FINDING CONTEXT block below to anchor your answer.
5. NEVER invent section numbers. If you don't see it in the excerpts, you
   don't know it.
6. End with a one-line caveat for any answer that interprets requirements:
   "Verify with your local AHJ before relying on this for permit purposes."
"""


# ============================================================
# Request / response models
# ============================================================

class ChatBody(BaseModel):
    question: str = Field(..., min_length=2, max_length=2000)
    # Optional: anchor the question to a specific finding by its code citation
    # (e.g. "IBC 1011.5.2"). Stable across re-runs, unlike a per-run finding id.
    finding_ref: Optional[str] = None


class ChatMessageOut(BaseModel):
    id: str
    role: str
    content: str
    citations: List[Dict[str, Any]] = []
    author_display: Optional[str] = None
    created_at: Optional[str] = None


# ============================================================
# Endpoints
# ============================================================

async def _assert_access(actor: Actor, job_id: str) -> Dict[str, Any]:
    """Either owner-of-job or guest-with-matching-token."""
    if actor.is_owner:
        job = db.get_job_for_user(job_id, actor.user_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        return job
    # guest
    if actor.job_id != job_id:
        raise HTTPException(status_code=403, detail="Token does not grant access to this report")
    job = db.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


def _retrieve_excerpts(question: str, k: int = 5) -> List[CodeChunk]:
    """Pull the most relevant code chunks for this question.

    We don't filter by category — clarifying questions can span departments
    ('what counts as a corridor' could be IBC or ADA). Let BM25 sort it.
    """
    return get_retriever().search(question, k=k, min_score=0.3)


def _format_finding_context(finding_row: Optional[Dict[str, Any]]) -> str:
    if not finding_row:
        return ""
    parts = [
        "FINDING CONTEXT (the user is asking about this specific finding):",
        f"  Section: {finding_row.get('code_id') or finding_row.get('code_section') or 'unknown'}",
        f"  Department: {finding_row.get('department')}",
        f"  Status: {finding_row.get('status')} (severity: {finding_row.get('severity')})",
        f"  Description: {finding_row.get('description', '')[:600]}",
    ]
    rec = finding_row.get("recommendation")
    if rec:
        parts.append(f"  Recommendation already in report: {rec[:400]}")
    return "\n".join(parts)


def _format_excerpts(chunks: List[CodeChunk]) -> str:
    if not chunks:
        return "(no matching code sections found in the reference library)"
    lines = []
    for c in chunks:
        lines.append(f"[{c.citation}] {c.title}\n{c.text}")
    return "\n\n".join(lines)


@router.get("/reports/{job_id}/chat")
@limiter.limit("60/minute")
async def get_chat_history(
    job_id: str,
    request: Request,
    actor: Actor = Depends(get_actor),
):
    await _assert_access(actor, job_id)
    messages = db.list_chat_messages(job_id, limit=200)
    return {"messages": messages}


@router.post("/reports/{job_id}/chat")
@limiter.limit("5/minute;30/hour;100/day")
async def post_chat(
    job_id: str,
    body: ChatBody,
    request: Request,
    actor: Actor = Depends(get_actor),
):
    """Ask the assistant a question. Returns the assistant's reply and persists
    both messages so the conversation is visible to all collaborators on this job.
    """
    await _assert_access(actor, job_id)

    # Optional: pull the specific finding the user is anchored on, matched by
    # its code citation against the DB findings for this job.
    finding_row = None
    if body.finding_ref:
        rows = db.list_findings_for_job(job_id)
        for r in rows:
            if (r.get("code_id") or "").strip().lower() == body.finding_ref.strip().lower():
                finding_row = r
                break

    # Retrieve relevant chunks. If the question references a specific finding,
    # always include that finding's code section as the top excerpt.
    excerpts = _retrieve_excerpts(body.question, k=5)
    if body.finding_ref:
        anchor = get_corpus().get(body.finding_ref)
        if anchor and anchor not in excerpts:
            excerpts.insert(0, anchor)
            excerpts = excerpts[:6]

    user_prompt = f"""USER QUESTION:
{body.question}

{_format_finding_context(finding_row)}

CODE EXCERPTS (use ONLY these for your answer):

{_format_excerpts(excerpts)}
"""

    # Save the user message FIRST (so even if the LLM call fails, the
    # question is on the record for the next viewer)
    db.add_chat_message(
        job_id=job_id,
        role="user",
        content=body.question,
        author_user_id=actor.user_id,
        author_share_id=actor.share_id,
        author_display=actor.display,
    )

    # Call Claude Sonnet (cheap)
    if not settings.anthropic_api_key:
        # Graceful degradation in dev
        reply = (
            "AI assistant is not configured yet (ANTHROPIC_API_KEY missing). "
            "Once it's wired up I'll answer clarifying questions like this one "
            "with quotes from the relevant code sections."
        )
    else:
        try:
            client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
            resp = await client.messages.create(
                model=settings.anthropic_model_cheap,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_prompt}],
                max_tokens=800,
            )
            reply = (resp.content[0].text if resp.content else "").strip()
            if not reply:
                reply = "I wasn't able to generate a response. Please rephrase the question."
        except Exception as e:
            logger.error(f"chat LLM call failed: {e}")
            reply = (
                "I had trouble reaching the assistant just now. Please try again "
                "in a moment, or check the cited sections directly:\n\n"
                + "\n".join(f"- {c.citation}: {c.title}" for c in excerpts[:3])
            )

    # Build citation pills for the UI
    citations = [
        {"citation": c.citation, "title": c.title, "section": c.section, "text": c.text}
        for c in excerpts
    ]
    assistant_row = db.add_chat_message(
        job_id=job_id,
        role="assistant",
        content=reply,
        citations=citations,
        author_display="Architechtura AI",
    )

    return {
        "reply": reply,
        "citations": citations,
        "message_id": assistant_row.get("id"),
    }
