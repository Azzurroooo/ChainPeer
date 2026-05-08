"""FastAPI routes for job management."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/jobs", tags=["jobs"])

class CancelRequest(BaseModel):
    reason: str = "API Cancellation"

def get_job_service(request: Request):
    return request.app.state.job_service


@router.get("/{job_id}")
async def get_job(job_id: str, job_service=Depends(get_job_service)):
    job = job_service.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
        
    return {
        "job_id": job.job_id,
        "session_id": job.session_id,
        "request_id": job.request_id,
        "tool_call_id": job.tool_call_id,
        "tool_name": job.tool_name,
        "status": job.status,
        "started_at": job.started_at,
        "ended_at": job.ended_at,
        "output_ref": job.output_ref,
        "metadata": job.metadata
    }


@router.post("/{job_id}/cancel")
async def cancel_job(job_id: str, req: CancelRequest, job_service=Depends(get_job_service)):
    job = job_service.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
        
    # In Phase 4, we don't have true preemptive bash kill linked up in job_service yet.
    # We update the status to trigger cancellation logic wherever the job is being watched.
    job_service.update_status(job_id, "cancelled", error=req.reason)
    return {"status": "cancelled", "reason": req.reason}


@router.get("/{job_id}/events")
async def stream_job_events(job_id: str, offset: int = 0, job_service=Depends(get_job_service)):
    """Fetch incremental output for a long running job."""
    job = job_service.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
        
    content, new_offset = job_service.read_output(job_id, offset)
    return {
        "job_id": job_id,
        "status": job.status,
        "content": content,
        "offset": new_offset
    }
