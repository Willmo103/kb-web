"""
FastAPI Router for Autonomous Background Worker management and status endpoints.
"""

import logging
from typing import Any, Dict
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import JSONResponse, RedirectResponse

from ..base import verify_auth
from ..worker import autonomous_worker

logger = logging.getLogger("kb_web.routers.worker")

router = APIRouter(tags=["worker"])


@router.get("/api/worker/status", response_model=None)
def get_worker_status(request: Request) -> Dict[str, Any]:
    """Returns the operational status, interval, metrics, and last run timestamp of the autonomous worker."""
    return autonomous_worker.get_status()


@router.post("/api/worker/cycle", dependencies=[Depends(verify_auth)], response_model=None)
async def trigger_worker_cycle() -> Dict[str, Any]:
    """Triggers an immediate autonomous maintenance cycle on-demand (1 wiki, 1 tag set)."""
    result = await autonomous_worker.run_cycle()
    return result


@router.post("/api/worker/toggle", dependencies=[Depends(verify_auth)], response_model=None)
def toggle_worker_state(enabled: bool = Form(...)) -> Dict[str, Any]:
    """Enables or pauses the autonomous background worker loop."""
    autonomous_worker.enabled = enabled
    logger.info(f"[AUTONOMOUS WORKER] State toggled by admin: enabled={enabled}")
    return {"status": "ok", "enabled": autonomous_worker.enabled}


@router.post("/admin/worker/trigger", dependencies=[Depends(verify_auth)], response_class=RedirectResponse)
async def admin_trigger_worker_now() -> RedirectResponse:
    """Admin form endpoint to trigger an immediate worker cycle and redirect back to admin."""
    res = await autonomous_worker.run_cycle()
    msg = "Autonomous+maintenance+cycle+executed+successfully."
    if res.get("curated_wiki_url"):
        msg += f"+Curated+wiki+for+{res['curated_wiki_url']}."
    return RedirectResponse(
        url=f"/admin#tab-prompts",
        status_code=303,
    )
