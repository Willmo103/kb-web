"""
Maintenance Agent Sidecar Engine for kb-web.
Automatically analyzes uncaught server errors, searches source code, inspects
artifacts, and produces immediate diagnostic feedback.
"""

import datetime
import json
import logging
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy import or_, text

from .base import db_session
from .config import Config
from .models_orm import ServerErrorLog

logger = logging.getLogger("kb_web.maintenance_agent")

REPO_ROOT = Path(__file__).resolve().parents[2]


# -----------------------------------------------------------------------------
# Maintenance Agent Tools
# -----------------------------------------------------------------------------

def tool_search_source_code(
    query: str,
    path_filter: Optional[str] = None,
    max_results: int = 15,
) -> Dict[str, Any]:
    """
    Searches the kb-web source code (src/kb_web, tests, migrations) for a symbol or text pattern.
    """
    search_dirs = [REPO_ROOT / "src", REPO_ROOT / "tests", REPO_ROOT / "migrations"]
    results = []

    pattern = re.compile(re.escape(query), re.IGNORECASE)

    for search_dir in search_dirs:
        if not search_dir.exists():
            continue
        for root, _, files in os.walk(search_dir):
            for file in files:
                if not file.endswith((".py", ".html", ".j2.html", ".toml", ".yml", ".sh", ".json")):
                    continue
                file_path = Path(root) / file
                rel_path = file_path.relative_to(REPO_ROOT).as_posix()
                if path_filter and path_filter.lower() not in rel_path.lower():
                    continue

                try:
                    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                        for line_num, line in enumerate(f, start=1):
                            if pattern.search(line):
                                results.append({
                                    "file": rel_path,
                                    "line": line_num,
                                    "content": line.strip()[:200],
                                })
                                if len(results) >= max_results:
                                    return {"query": query, "matches": results, "total": len(results)}
                except Exception as e:
                    logger.debug(f"Error reading {file_path}: {e}")

    return {"query": query, "matches": results, "total": len(results)}


def tool_view_artifacts(
    artifact_path: Optional[str] = None,
    search_term: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Inspects planning artifacts in .artifacts/ or test reports in uat/reports/.
    If artifact_path is None, lists available artifacts.
    """
    artifacts_dir = REPO_ROOT / ".artifacts"
    uat_reports_dir = REPO_ROOT / "uat" / "reports"

    # If no path given, list all artifacts
    if not artifact_path:
        artifact_files = []
        if artifacts_dir.exists():
            for p in artifacts_dir.rglob("*.md"):
                artifact_files.append(p.relative_to(REPO_ROOT).as_posix())
        if uat_reports_dir.exists():
            for p in uat_reports_dir.glob("*.md"):
                artifact_files.append(p.relative_to(REPO_ROOT).as_posix())

        if search_term:
            filtered = [f for f in artifact_files if search_term.lower() in f.lower()]
            return {"available_artifacts": filtered[:25], "total": len(filtered)}
        return {"available_artifacts": artifact_files[:25], "total": len(artifact_files)}

    # Path provided: read file
    target = REPO_ROOT / artifact_path.replace("\\", "/").lstrip("/")
    if not target.exists():
        return {"error": f"Artifact not found: {artifact_path}"}

    try:
        content = target.read_text(encoding="utf-8", errors="ignore")
        # Return first 4000 characters
        truncated = content[:4000]
        return {
            "path": artifact_path,
            "content": truncated,
            "truncated": len(content) > 4000,
            "total_length": len(content),
        }
    except Exception as e:
        return {"error": f"Failed reading artifact: {str(e)}"}


def tool_search_errors(
    query: str,
    limit: int = 10,
) -> Dict[str, Any]:
    """
    Searches the historical server_error_logs table for keywords across error_type,
    error_message, and stack_trace.
    """
    try:
        with db_session() as session:
            pattern = f"%{query}%"
            logs = (
                session.query(ServerErrorLog)
                .filter(
                    or_(
                        ServerErrorLog.error_type.ilike(pattern),
                        ServerErrorLog.error_message.ilike(pattern),
                        ServerErrorLog.stack_trace.ilike(pattern),
                        ServerErrorLog.request_url.ilike(pattern),
                    )
                )
                .order_by(ServerErrorLog.id.desc())
                .limit(limit)
                .all()
            )

            records = [
                {
                    "id": l.id,
                    "timestamp": l.timestamp,
                    "error_type": l.error_type,
                    "error_message": (l.error_message or "")[:150],
                    "request_url": l.request_url,
                    "status": l.status,
                    "has_feedback": bool(l.agent_feedback),
                }
                for l in logs
            ]
            return {"query": query, "matches": records, "count": len(records)}
    except Exception as e:
        return {"error": f"Failed searching error logs: {str(e)}"}


# -----------------------------------------------------------------------------
# Diagnostic Prompt Construction & Ollama Execution
# -----------------------------------------------------------------------------

def format_error_prompt(error_log: Dict[str, Any]) -> str:
    """
    Formats the prompt for the maintenance agent, enforcing a strict 3000-character limit.
    """
    raw_parts = [
        f"Server Error Incident #{error_log.get('id', 'N/A')}",
        f"Timestamp: {error_log.get('timestamp', 'N/A')}",
        f"Request: {error_log.get('request_method', 'GET')} {error_log.get('request_url', 'N/A')}",
        f"Client IP: {error_log.get('client_ip', 'unknown')}",
        f"Error Type: {error_log.get('error_type', 'UnknownError')}",
        f"Error Message: {error_log.get('error_message', 'No message')}",
        "",
        "Stack Trace:",
        error_log.get("stack_trace", "No stack trace available."),
    ]
    full_text = "\n".join(raw_parts)

    # Strictly limit to 3000 characters as requested
    if len(full_text) > 3000:
        full_text = full_text[:2950] + "\n... [TRUNCATED TO 3000 CHARS]"
    return full_text


def analyze_error_with_agent(
    error_id: int,
    config: Optional[Config] = None,
    send_gotify: bool = True,
) -> str:
    """
    Analyzes a logged server error using the maintenance agent with Ollama and tools.
    Updates the database record with the resulting diagnosis.
    """
    cfg = config or Config()

    # 1. Fetch error from DB
    with db_session() as session:
        err = session.query(ServerErrorLog).filter_by(id=error_id).first()
        if not err:
            logger.warning(f"ServerErrorLog with ID {error_id} not found.")
            return "Error record not found."

        error_dict = {
            "id": err.id,
            "timestamp": err.timestamp,
            "error_type": err.error_type,
            "error_message": err.error_message,
            "stack_trace": err.stack_trace,
            "request_method": err.request_method,
            "request_url": err.request_url,
            "client_ip": err.client_ip,
        }

    # 2. Format capped prompt
    prompt_content = format_error_prompt(error_dict)

    # 3. Perform automated tool searches to enrich context
    extracted_terms = []
    if "does not exist" in error_dict.get("error_message", ""):
        match = re.search(r"column\s+([\w\.]+)\s+does not exist", error_dict["error_message"])
        if match:
            extracted_terms.append(match.group(1).split(".")[-1])

    code_context = []
    for term in extracted_terms[:2]:
        search_res = tool_search_source_code(term, max_results=5)
        if search_res.get("matches"):
            for m in search_res["matches"][:3]:
                code_context.append(f"- {m['file']}:{m['line']}: {m['content']}")

    context_str = ""
    if code_context:
        context_str = "\n\nRelevant Code Search Matches:\n" + "\n".join(code_context)

    system_instructions = (
        "You are the kb-web Site Maintenance Agent. You provide immediate, accurate root cause "
        "diagnostics and precise code/database fixes for uncaught server errors.\n"
        "Structure your response with:\n"
        "1. 🔍 Root Cause Analysis (what broke and why)\n"
        "2. 📍 Affected Component / Source Location\n"
        "3. 🛠️ Actionable Recommended Fix (exact SQL or Python code change required)"
    )

    user_message = f"Please analyze this server error:\n\n{prompt_content}{context_str}"

    diagnosis = ""
    # 4. Call Ollama
    try:
        import ollama
        client = ollama.Client(host=cfg.ollama_host, timeout=5.0)
        model_name = cfg.ollama_model or "gemma4:latest"

        resp = client.chat(
            model=model_name,
            messages=[
                {"role": "system", "content": system_instructions},
                {"role": "user", "content": user_message},
            ],
            options={"temperature": 0.2},
        )
        diagnosis = resp.get("message", {}).get("content", "").strip()
    except Exception as e:
        logger.warning(f"Ollama call failed or model unavailable ({e}). Generating rule-based diagnosis.")
        # Fallback intelligent rule-based diagnosis
        msg = error_dict.get("error_message", "")
        if "UndefinedColumn" in error_dict.get("error_type", "") or "does not exist" in msg:
            col_match = re.search(r"column\s+([\w\.]+)\s+does not exist", msg)
            col_name = col_match.group(1) if col_match else "column"
            diagnosis = (
                f"### 🔍 Root Cause Analysis\n"
                f"Database schema mismatch: The query expects column `{col_name}`, but it is missing from the database table.\n\n"
                f"### 📍 Affected Component\n"
                f"Route `{error_dict.get('request_url')}` queried a table missing `{col_name}`.\n\n"
                f"### 🛠️ Actionable Recommended Fix\n"
                f"Run an ALTER TABLE statement or apply pending migrations:\n"
                f"```sql\nALTER TABLE {col_name.split('.')[0] if '.' in col_name else 'table'} ADD COLUMN IF NOT EXISTS {col_name.split('.')[-1]} VARCHAR(32);\n```\n"
                f"And ensure `models_orm.ensure_views_and_indexes()` executes DDL on PostgreSQL startup."
            )
        else:
            diagnosis = (
                f"### 🔍 Root Cause Analysis\n"
                f"Uncaught `{error_dict.get('error_type')}` during `{error_dict.get('request_method')} {error_dict.get('request_url')}`: {msg}\n\n"
                f"### 🛠️ Recommended Action\n"
                f"Inspect the traceback in `server_error_logs` (ID {error_id})."
            )

    # 5. Save diagnosis to database
    with db_session() as session:
        err = session.query(ServerErrorLog).filter_by(id=error_id).first()
        if err:
            err.agent_feedback = diagnosis
            err.status = "analyzed"
            session.commit()

    # 6. Post follow-up to Gotify if enabled
    if send_gotify:
        try:
            notifier = cfg.get_notifier()
            if notifier.POST_ENABLED:
                title = f"🛠️ Agent Diagnosis: {error_dict.get('error_type', 'Error')} [#{error_id}]"
                notifier.send_notification(title, diagnosis[:1500])
        except Exception as e:
            logger.debug(f"Failed sending Gotify diagnosis: {e}")

    return diagnosis


def dispatch_error_to_maintenance_agent(
    error_id: int,
    background: bool = True,
) -> None:
    """
    Dispatches an error to the maintenance agent asynchronously in a background thread.
    """
    if background:
        thread = threading.Thread(
            target=analyze_error_with_agent,
            args=(error_id,),
            daemon=True,
            name=f"MaintenanceAgent-{error_id}",
        )
        thread.start()
    else:
        analyze_error_with_agent(error_id)


# -----------------------------------------------------------------------------
# Background Sidecar Daemon
# -----------------------------------------------------------------------------

def run_maintenance_daemon(
    poll_interval: int = 5,
    run_once: bool = False,
) -> None:
    """
    Continuously monitors the server_error_logs table for unanalyzed errors
    and processes them as a background sidecar.
    """
    logger.info("Starting Maintenance Agent Sidecar Daemon...")
    print(f"[INFO] Maintenance Agent Sidecar Daemon active (poll_interval={poll_interval}s)")

    while True:
        try:
            with db_session() as session:
                pending_errors = (
                    session.query(ServerErrorLog)
                    .filter_by(status="open")
                    .order_by(ServerErrorLog.id.asc())
                    .limit(5)
                    .all()
                )
                pending_ids = [e.id for e in pending_errors]

            for eid in pending_ids:
                print(f"[AGENT] Analyzing server error #{eid}...")
                analyze_error_with_agent(eid)
                print(f"[AGENT] Completed diagnosis for error #{eid}.")

        except Exception as e:
            logger.error(f"Error in maintenance agent daemon loop: {e}")

        if run_once:
            break
        time.sleep(poll_interval)


if __name__ == "__main__":
    run_maintenance_daemon()
