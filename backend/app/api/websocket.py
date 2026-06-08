import asyncio
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from app.services import db
from app.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter()

# How often to poll the DB for new logs/status while a socket is open.
# Reviews are short (~90s) and concurrent reviews are rare, so a 1s poll
# is gentle on the DB while still feeling real-time in the dashboard.
POLL_INTERVAL_SEC = 1.0
# Safety ceiling so a wedged job can never pin a socket open forever.
MAX_STREAM_SEC = 15 * 60


@router.websocket("/ws/{job_id}")
async def websocket_endpoint(websocket: WebSocket, job_id: str):
    """Stream job logs + status to the dashboard in near-real-time.

    Reads from the DB (the durable source of truth written by the
    background pipeline) rather than any in-process state, so it works
    regardless of which worker handled the upload. The frontend treats
    this as best-effort and falls back to HTTP polling if the socket
    never opens or drops mid-review.
    """
    await websocket.accept()
    logger.info(f"WebSocket connected for job: {job_id}")

    sent_log_count = 0
    elapsed = 0.0

    try:
        while True:
            job = db.get_job(job_id)
            if not job:
                await websocket.send_json({"type": "error", "message": "Job not found"})
                break

            # Stream any logs we haven't sent yet.
            logs = db.list_logs_for_job(job_id, limit=500)
            if len(logs) > sent_log_count:
                for log in logs[sent_log_count:]:
                    await websocket.send_json({
                        "type": "log",
                        "job_id": job_id,
                        "data": {
                            "timestamp": log.get("ts"),
                            "agent": log.get("agent"),
                            "level": log.get("level"),
                            "message": log.get("message"),
                            "data": log.get("data") or {},
                        },
                    })
                sent_log_count = len(logs)

            status = job.get("status")
            await websocket.send_json({
                "type": "status",
                "job_id": job_id,
                "data": {
                    "status": status,
                    "progress": job.get("progress", 0),
                    "current_agent": job.get("current_agent"),
                    "agents_completed": job.get("agents_completed") or [],
                },
            })

            if status in ("completed", "failed"):
                if status == "completed":
                    await websocket.send_json({
                        "type": "completed",
                        "job_id": job_id,
                        "data": {"message": "Processing complete"},
                    })
                else:
                    await websocket.send_json({
                        "type": "failed",
                        "job_id": job_id,
                        "data": {"error": job.get("error")},
                    })
                break

            await asyncio.sleep(POLL_INTERVAL_SEC)
            elapsed += POLL_INTERVAL_SEC
            if elapsed >= MAX_STREAM_SEC:
                logger.warning(f"WebSocket stream for job {job_id} hit {MAX_STREAM_SEC}s cap; closing")
                break

    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected for job: {job_id}")
    except Exception as e:
        logger.error(f"WebSocket error for job {job_id}: {e}")
