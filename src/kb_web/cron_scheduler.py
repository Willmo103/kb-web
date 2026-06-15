"""
Cron jobs scheduling and background runner engine for the Knowledge Base Web Importer.
"""

import json
import time
import asyncio
import traceback
from datetime import datetime
from typing import Dict, List
import sqlite_utils
import hashlib

from .utils import fetch_url
from .models import HTMLPage


def format_prompt(template: str, current_page: HTMLPage, last_run_dict: Dict) -> str:
    """Safely substitutes prompt template placeholders with fetched page values and last run content."""
    vars = {
        "url": current_page.url,
        "title": current_page.title or current_page.url,
        "html_content": current_page.html_content or "",
        "md_content": current_page.md_content or "",
        "fetched_at": current_page.fetched_at or "",
        "last_run.md_content": last_run_dict.get("md_content", ""),
        "last_run.html_content": last_run_dict.get("html_content", ""),
        "last_run.prompt_output": last_run_dict.get("prompt_output", ""),
    }
    
    result = template
    for k, v in vars.items():
        placeholder = "{" + k + "}"
        if placeholder in result:
            result = result.replace(placeholder, str(v))
    return result


async def run_single_job(db: sqlite_utils.Database, job_id: int, config) -> Dict:
    """Executes a single cron job, fetches content, prompts Ollama, writes DB/files, and logs outcomes."""
    start_time = time.time()
    job = db["cron_jobs"].get(job_id)
    url = job["url"]
    prompt_template = job["prompt_template"]
    db_store = bool(job["db_store"])
    file_store = bool(job["file_store"])
    notify_on = job["notify_on"]

    status = "success"
    error_message = None
    prompt_output = None
    files_created: List[str] = []
    current_page = None

    # Retrieve last successful run details for template formatting
    last_run_dict = {}
    try:
        runs = list(db["cron_job_runs"].rows_where(
            "cron_job_id = ? AND status = 'success' ORDER BY id DESC LIMIT 1",
            [job_id]
        ))
        if runs:
            # We fetch the actual html/markdown from the run record
            last_run = runs[0]
            last_run_dict = {
                "md_content": last_run.get("prompt_output", ""),
                "html_content": last_run.get("prompt_output", ""), # fallback
                "prompt_output": last_run.get("prompt_output", ""),
            }
    except Exception as e:
        print(f"Cron [{job_id}]: failed to fetch last run: {e}")

    try:
        # 1. Fetch url
        current_page = fetch_url(url)
        
        # 2. Format prompt
        formatted_prompt = format_prompt(prompt_template, current_page, last_run_dict)
        
        # 3. Prompt Ollama
        import ollama
        client = ollama.Client(host=config.ollama_host)
        
        # Ensure model is available
        from .utils import ensure_model_available
        ensure_model_available(client, config.ollama_model)

        response = client.chat(
            model=config.ollama_model,
            messages=[
                {"role": "system", "content": "You are a helpful knowledge curation assistant."},
                {"role": "user", "content": formatted_prompt}
            ],
            think=False,
        )
        prompt_output = response.message.content

        # 4. Save to DB if requested
        if db_store:
            # Generate a unique URL identifier for this run to keep history
            run_timestamp = datetime.now().isoformat()
            safe_title = job["title"] or "Cron Job Output"
            unique_url = f"cron://{job_id}/{run_timestamp.replace(':', '-')}"
            
            # Construct page record
            page_data = {
                "url": unique_url,
                "title": f"{safe_title} ({run_timestamp[:10]})",
                "html_content": f"<html><body><pre>{prompt_output}</pre></body></html>",
                "md_content": prompt_output,
                "links": "[]",
                "html_content_hash": hashlib.sha256((prompt_output or "").encode("utf-8")).hexdigest(),
                "md_content_hash": hashlib.sha256((prompt_output or "").encode("utf-8")).hexdigest(),
                "fetched_at": run_timestamp,
                "description": prompt_output, # Rendered as wiki markdown
                "keywords": "[]",
                "tags": json.dumps(["cron-run", f"job-{job_id}"]),
            }
            db["fetched_pages"].upsert(page_data, pk="url")
            
            # Generate similarity embedding for the generated output
            from .utils import update_article_embedding
            update_article_embedding(db, unique_url, config, client)
            print(f"Cron [{job_id}]: saved page object to database: {unique_url}")

        # 5. Save to file system if requested
        if file_store:
            cron_files_dir = config.configs_dir.parent / "cron_files"
            cron_files_dir.mkdir(parents=True, exist_ok=True)
            
            filename = f"cron_{job_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
            filepath = cron_files_dir / filename
            
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(f"# Cron Run: {job['title']}\n")
                f.write(f"Date: {datetime.now().isoformat()}\n")
                f.write(f"Source URL: {url}\n\n")
                f.write("## Generated Output\n\n")
                f.write(prompt_output or "")
                
            files_created.append(filename)
            print(f"Cron [{job_id}]: saved output file to: {filepath}")

    except Exception as e:
        status = "failure"
        error_message = traceback.format_exc()
        print(f"Cron Job [{job_id}] failed: {e}\n{error_message}")

    duration = time.time() - start_time
    run_timestamp = datetime.now().isoformat()

    # Log run details to database
    run_id = db["cron_job_runs"].insert({
        "cron_job_id": job_id,
        "status": status,
        "fetched_at": run_timestamp,
        "prompt_output": prompt_output,
        "error_message": error_message,
        "files_created": json.dumps(files_created),
        "duration": duration,
    }).last_rowid

    # Update parent job status metadata
    db["cron_jobs"].update(job_id, {
        "last_run_at": run_timestamp,
        "updated_at": run_timestamp
    })

    # Dispatch Gotify notification if rules apply
    should_notify = (
        (status == "success" and notify_on in ("success", "both")) or
        (status == "failure" and notify_on in ("failure", "both"))
    )

    if should_notify:
        try:
            notifier = config.get_notifier()
            if notifier.token and notifier.url:
                title = f"⏰ Cron Job: {job['title']} [{status.upper()}]"
                if status == "success":
                    msg = f"Job successfully finished in {duration:.2f} seconds.\n\nSummary:\n{prompt_output[:400]}..."
                else:
                    msg = f"Job failed to run. Error:\n{error_message}"
                notifier.send_notification(title, msg)
        except Exception as notify_err:
            print(f"Cron [{job_id}]: failed to send gotify notification: {notify_err}")

    return {
        "run_id": run_id,
        "status": status,
        "duration": duration,
        "files_created": files_created,
        "error": error_message
    }


async def run_cron_scheduler(config, get_db_fn):
    """Loop runner checking for due scheduled active cron jobs every 30 seconds."""
    print("Starting scheduled background cron runner...")
    while True:
        try:
            db = get_db_fn()
            if "cron_jobs" in db.table_names():
                active_jobs = list(db["cron_jobs"].rows_where("is_active = 1"))
                
                for job in active_jobs:
                    job_id = job["id"]
                    interval = job.get("interval_minutes", 60)
                    last_run_at = job.get("last_run_at")
                    
                    is_due = False
                    if not last_run_at:
                        is_due = True
                    else:
                        try:
                            last_run = datetime.fromisoformat(last_run_at)
                            elapsed = (datetime.now() - last_run).total_seconds()
                            if elapsed >= interval * 60:
                                is_due = True
                        except Exception:
                            is_due = True
                            
                    if is_due:
                        print(f"Cron Scheduler: Job [{job_id}] '{job['title']}' is due. Initiating execution...")
                        # Run as a background task to prevent blocking other jobs
                        asyncio.create_task(run_single_job(db, job_id, config))
                        
        except Exception as e:
            print(f"Cron Scheduler Error: {e}")
            
        await asyncio.sleep(30)
