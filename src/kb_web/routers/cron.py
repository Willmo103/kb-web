"""
FastAPI Router for cron configuration, history logging, and file downloads in kb-web.
"""

import os
import json
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, Form, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse

from ..base import (
    config,
    _jinja_env,
    _get_db,
    verify_auth,
)
from ..cron_scheduler import run_single_job

router = APIRouter()


@router.get("/admin/cron", response_class=HTMLResponse, dependencies=[Depends(verify_auth)])
def get_cron_dashboard() -> HTMLResponse:
    """Lists all configured cron jobs and summary stats."""
    db = _get_db()
    jobs = []
    if "cron_jobs" in db.table_names():
        try:
            # Fetch all jobs along with their run counts and last status
            jobs = list(db.execute_returning_dicts(
                """
                SELECT c.*, 
                       (SELECT COUNT(*) FROM cron_job_runs WHERE cron_job_id = c.id) as total_runs,
                       (SELECT status FROM cron_job_runs WHERE cron_job_id = c.id ORDER BY id DESC LIMIT 1) as last_status
                FROM cron_jobs c
                ORDER BY c.id DESC
                """
            ))
        except Exception as e:
            print(f"Error reading cron jobs: {e}")

    template = _jinja_env.get_template("cron_jobs.j2.html")
    return HTMLResponse(content=template.render(jobs=jobs, is_admin=True))


@router.post("/admin/cron/create", dependencies=[Depends(verify_auth)])
def create_cron_job(
    title: str = Form(...),
    url: str = Form(...),
    interval_minutes: int = Form(...),
    prompt_template: str = Form(...),
    output_type: str = Form("article"),
    db_store: Optional[str] = Form(None),
    file_store: Optional[str] = Form(None),
    notify_on: str = Form("none"),
) -> RedirectResponse:
    """Inserts a new scheduled fetching job."""
    db = _get_db()
    
    db_store_val = 1 if db_store else 0
    file_store_val = 1 if file_store else 0
    
    timestamp = datetime.now().isoformat()
    try:
        db["cron_jobs"].insert({
            "title": title.strip(),
            "url": url.strip(),
            "interval_minutes": interval_minutes,
            "prompt_template": prompt_template,
            "output_type": output_type,
            "db_store": db_store_val,
            "file_store": file_store_val,
            "notify_on": notify_on,
            "is_active": 1,
            "last_run_at": None,
            "created_at": timestamp,
            "updated_at": timestamp,
        })
    except Exception as e:
        print(f"Failed to create cron job: {e}")
        
    return RedirectResponse(url="/admin/cron", status_code=303)


@router.post("/admin/cron/edit/{job_id}", dependencies=[Depends(verify_auth)])
def edit_cron_job(
    job_id: int,
    title: str = Form(...),
    url: str = Form(...),
    interval_minutes: int = Form(...),
    prompt_template: str = Form(...),
    output_type: str = Form("article"),
    db_store: Optional[str] = Form(None),
    file_store: Optional[str] = Form(None),
    notify_on: str = Form("none"),
) -> RedirectResponse:
    """Updates an existing scheduled fetching job."""
    db = _get_db()
    
    db_store_val = 1 if db_store else 0
    file_store_val = 1 if file_store else 0
    
    try:
        db["cron_jobs"].update(job_id, {
            "title": title.strip(),
            "url": url.strip(),
            "interval_minutes": interval_minutes,
            "prompt_template": prompt_template,
            "output_type": output_type,
            "db_store": db_store_val,
            "file_store": file_store_val,
            "notify_on": notify_on,
            "updated_at": datetime.now().isoformat(),
        })
    except Exception as e:
        print(f"Failed to update cron job: {e}")
        
    return RedirectResponse(url=f"/admin/cron/view/{job_id}", status_code=303)


@router.post("/admin/cron/toggle/{job_id}", dependencies=[Depends(verify_auth)])
def toggle_cron_job(job_id: int) -> RedirectResponse:
    """Enables or disables an active scheduled task."""
    db = _get_db()
    try:
        job = db["cron_jobs"].get(job_id)
        new_active = 0 if job["is_active"] else 1
        db["cron_jobs"].update(job_id, {"is_active": new_active, "updated_at": datetime.now().isoformat()})
    except Exception as e:
        print(f"Failed to toggle cron job active state: {e}")
        
    return RedirectResponse(url="/admin/cron", status_code=303)


@router.post("/admin/cron/delete/{job_id}", dependencies=[Depends(verify_auth)])
def delete_cron_job(job_id: int) -> RedirectResponse:
    """Removes a scheduled job and deletes its runs logs history from the DB."""
    db = _get_db()
    try:
        # Delete related run logs first to avoid FK errors
        db.execute("DELETE FROM cron_job_runs WHERE cron_job_id = ?", [job_id])
        db["cron_jobs"].delete(job_id)
    except Exception as e:
        print(f"Failed to delete cron job: {e}")
        
    return RedirectResponse(url="/admin/cron", status_code=303)


@router.post("/admin/cron/run/{job_id}", dependencies=[Depends(verify_auth)])
async def trigger_cron_job_run(job_id: int) -> RedirectResponse:
    """Manually triggers immediate execution of a scheduled job in the background."""
    db = _get_db()
    try:
        # Run job immediately (async)
        import asyncio
        asyncio.create_task(run_single_job(db, job_id, config))
    except Exception as e:
        print(f"Failed to trigger cron job execution manually: {e}")
        
    return RedirectResponse(url=f"/admin/cron/view/{job_id}?msg=Cron+job+execution+manually+triggered.", status_code=303)


@router.get("/admin/cron/view/{job_id}", response_class=HTMLResponse, dependencies=[Depends(verify_auth)])
def view_cron_job_details(
    job_id: int,
    msg: Optional[str] = Query(None),
) -> HTMLResponse:
    """Renders details of a single scheduled job and list of past executions logs."""
    db = _get_db()
    try:
        job = db["cron_jobs"].get(job_id)
    except Exception:
        raise HTTPException(status_code=404, detail="Scheduled job not found.")

    runs = []
    if "cron_job_runs" in db.table_names():
        try:
            runs = list(db["cron_job_runs"].rows_where("cron_job_id = ? ORDER BY id DESC", [job_id]))
            for r in runs:
                # Deserialize created files list
                files_json = r.get("files_created")
                if files_json:
                    try:
                        r["files"] = json.loads(files_json)
                    except Exception:
                        r["files"] = []
                else:
                    r["files"] = []
        except Exception as e:
            print(f"Failed to fetch job runs logs: {e}")

    template = _jinja_env.get_template("view_cron_job.j2.html")
    return HTMLResponse(content=template.render(job=job, runs=runs, is_admin=True, msg=msg))


@router.get("/admin/cron/download/{filename}", dependencies=[Depends(verify_auth)])
def download_cron_file(filename: str) -> FileResponse:
    """Downloads a file generated by a scheduled fetch task."""
    # Sanitize inputs to prevent directory traversal
    safe_name = os.path.basename(filename)
    file_path = config.configs_dir.parent / "cron_files" / safe_name
    if file_path.exists():
        return FileResponse(
            path=str(file_path),
            filename=safe_name,
            media_type="application/octet-stream"
        )
    raise HTTPException(status_code=404, detail="File not found.")
