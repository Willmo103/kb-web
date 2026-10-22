"""
FastAPI Router for Autonomous Background Worker & Modular Server Jobs management.
"""

import logging
from typing import Any, Dict, Optional
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel

from ..base import verify_auth
from ..worker import autonomous_worker

logger = logging.getLogger("kb_web.routers.worker")

router = APIRouter(tags=["worker", "jobs"])


class JobConfigRequest(BaseModel):
    enabled: Optional[bool] = None
    interval_minutes: Optional[int] = None
    model: Optional[str] = None


@router.get("/api/worker/status", response_model=None)
def get_worker_status(request: Request) -> Dict[str, Any]:
    """Returns the operational status, interval, metrics, and jobs of the autonomous worker."""
    return autonomous_worker.get_status()


@router.post("/api/worker/cycle", dependencies=[Depends(verify_auth)], response_model=None)
async def trigger_worker_cycle() -> Dict[str, Any]:
    """Triggers an immediate autonomous maintenance cycle across due enabled jobs."""
    result = await autonomous_worker.run_cycle()
    return result


@router.post("/api/worker/toggle", dependencies=[Depends(verify_auth)], response_model=None)
def toggle_worker_state(enabled: bool = Form(...)) -> Dict[str, Any]:
    """Enables or pauses the global autonomous background worker scheduler loop."""
    autonomous_worker.enabled = enabled
    logger.info(f"[AUTONOMOUS WORKER] State toggled by admin: enabled={enabled}")
    return {"status": "ok", "enabled": autonomous_worker.enabled}


@router.get("/api/jobs", response_model=None)
def list_jobs(request: Request) -> Dict[str, Any]:
    """Returns the list of all registered autonomous server jobs, intervals, models, and metrics."""
    return {"jobs": autonomous_worker.get_jobs()}


@router.get("/api/jobs/{job_id}", response_model=None)
def get_job_detail(job_id: str) -> Dict[str, Any]:
    """Returns status and configuration details for a single server job."""
    job = autonomous_worker.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")
    return job.to_dict()


@router.post("/api/jobs/{job_id}/run", dependencies=[Depends(verify_auth)], response_model=None)
async def trigger_single_job(job_id: str) -> Dict[str, Any]:
    """Executes a single autonomous server job immediately on demand."""
    try:
        res = await autonomous_worker.run_job(job_id)
        return {"status": "success", "job_id": job_id, "result": res}
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")
    except Exception as e:
        logger.error(f"Error running job {job_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/jobs/{job_id}/config", dependencies=[Depends(verify_auth)], response_model=None)
def update_job_configuration(job_id: str, payload: JobConfigRequest) -> Dict[str, Any]:
    """Updates the scheduling interval, model, or enabled state for a specific job."""
    try:
        updated = autonomous_worker.update_job_config(
            job_id=job_id,
            enabled=payload.enabled,
            interval_minutes=payload.interval_minutes,
            model=payload.model,
        )
        return {"status": "success", "job": updated}
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")


@router.get("/api/jobs/{job_id}/executions", response_model=None)
def list_job_executions(job_id: str, limit: int = 50) -> Dict[str, Any]:
    """Returns recent target-level execution records for a specific job."""
    job = autonomous_worker.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")
    executions = autonomous_worker.get_target_executions(job_id=job_id, limit=limit)
    return {"job_id": job_id, "executions": executions, "count": len(executions)}


@router.post("/api/jobs/{job_id}/executions/clear", dependencies=[Depends(verify_auth)], response_model=None)
def clear_job_executions(job_id: str) -> Dict[str, Any]:
    """Clears target execution records and in-memory deduplication tracking for a job."""
    job = autonomous_worker.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")
    deleted = autonomous_worker.clear_target_executions(job_id=job_id)
    return {"status": "success", "job_id": job_id, "cleared_count": deleted}


@router.post("/admin/jobs/{job_id}/run", dependencies=[Depends(verify_auth)], response_class=RedirectResponse)
async def admin_run_job_now(job_id: str) -> RedirectResponse:
    """Admin form endpoint to trigger a specific job and redirect back to admin portal."""
    try:
        await autonomous_worker.run_job(job_id)
    except Exception as e:
        logger.warning(f"Admin triggered job {job_id} encountered error: {e}")
    return RedirectResponse(
        url="/admin#tab-prompts",
        status_code=303,
    )


@router.post("/admin/jobs/{job_id}/config", dependencies=[Depends(verify_auth)], response_class=RedirectResponse)
def admin_save_job_config(
    job_id: str,
    enabled: bool = Form(False),
    interval_minutes: int = Form(5),
    model: str = Form(""),
) -> RedirectResponse:
    """Admin form endpoint to update job configuration parameters."""
    try:
        autonomous_worker.update_job_config(
            job_id=job_id,
            enabled=enabled,
            interval_minutes=interval_minutes,
            model=model.strip(),
        )
    except Exception as e:
        logger.warning(f"Admin update job config {job_id} error: {e}")
    return RedirectResponse(
        url="/admin#tab-prompts",
        status_code=303,
    )


@router.post("/admin/jobs/{job_id}/executions/clear", dependencies=[Depends(verify_auth)], response_class=RedirectResponse)
def admin_clear_job_executions(job_id: str) -> RedirectResponse:
    """Admin form endpoint to clear target executions and reset job deduplication."""
    try:
        autonomous_worker.clear_target_executions(job_id=job_id)
    except Exception as e:
        logger.warning(f"Admin clear job executions {job_id} error: {e}")
    return RedirectResponse(
        url="/admin#tab-prompts",
        status_code=303,
    )


@router.post("/admin/worker/trigger", dependencies=[Depends(verify_auth)], response_class=RedirectResponse)
async def admin_trigger_worker_now() -> RedirectResponse:
    """Admin form endpoint to trigger an immediate worker cycle across all due jobs."""
    await autonomous_worker.run_cycle()
    return RedirectResponse(
        url="/admin#tab-prompts",
        status_code=303,
    )

