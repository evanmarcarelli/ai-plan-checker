import asyncio
import json
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from app.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter()

# Active WebSocket connections per job
active_connections: dict = {}


@router.websocket("/ws/{job_id}")
async def websocket_endpoint(websocket: WebSocket, job_id: str):
    """WebSocket endpoint for real-time job log streaming."""
    await websocket.accept()

    if job_id not in active_connections:
        active_connections[job_id] = []
    active_connections[job_id].append(websocket)

    logger.info(f"WebSocket connected for job: {job_id}")

    try:
        # Poll for updates while connection is open
        from app.api.routes import jobs
        last_log_count = 0

        while True:
            job = jobs.get(job_id)
            if not job:
                await websocket.send_json({"type": "error", "message": "Job not found"})
                break

            # Send new logs
            current_logs = job.logs
            if len(current_logs) > last_log_count:
                new_logs = current_logs[last_log_count:]
                for log in new_logs:
                    await websocket.send_json({
                        "type": "log",
                        "job_id": job_id,
                        "data": {
                            "timestamp": log.timestamp.isoformat(),
                            "agent": log.agent,
                            "level": log.level,
                            "message": log.message,
                            "data": log.data or {},
                        }
                    })
                last_log_count = len(current_logs)

            # Send status update
            await websocket.send_json({
                "type": "status",
                "job_id": job_id,
                "data": {
                    "status": job.status.value,
                    "progress": job.progress,
                    "current_agent": job.current_agent,
                    "agents_completed": job.agents_completed,
                }
            })

            # If job finished, send final report and close
            if job.status.value in ("completed", "failed"):
                if job.status.value == "completed" and job.report:
                    await websocket.send_json({
                        "type": "completed",
                        "job_id": job_id,
                        "data": {"message": "Processing complete"}
                    })
                elif job.status.value == "failed":
                    await websocket.send_json({
                        "type": "failed",
                        "job_id": job_id,
                        "data": {"error": job.error}
                    })
                break

            await asyncio.sleep(0.5)

    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected for job: {job_id}")
    except Exception as e:
        logger.error(f"WebSocket error for job {job_id}: {e}")
    finally:
        if job_id in active_connections:
            try:
                active_connections[job_id].remove(websocket)
            except ValueError:
                pass
