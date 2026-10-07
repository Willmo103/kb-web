"""
Gotify error notifications and persistent error logging utility for kb-web.
"""

import datetime
import json
import logging
from pathlib import Path
from typing import Optional
from fastapi import Request

logger = logging.getLogger("kb_web.gotify")


def record_server_error(
    config, exc: Exception, tb: str, request: Optional[Request] = None
) -> Optional[int]:
    """
    Persists an uncaught server exception into the database server_error_logs table,
    appends to ~/.kb/logs/server_errors.jsonl, sends a Gotify push notification,
    and automatically dispatches the error to the background Maintenance Agent sidecar.
    """
    timestamp = datetime.datetime.now().isoformat()
    error_type = type(exc).__name__
    error_message = str(exc)
    stack_trace = tb
    request_method = request.method if request else "N/A"
    request_url = str(request.url.path) if request else "N/A"
    query_params = json.dumps(dict(request.query_params)) if (request and request.query_params) else "{}"
    client_ip = request.client.host if (request and request.client) else "unknown"

    error_id = None
    # 1. Insert into database table
    try:
        from .base import db_session
        from .models_orm import ServerErrorLog

        with db_session() as session:
            err_record = ServerErrorLog(
                timestamp=timestamp,
                error_type=error_type,
                error_message=error_message,
                stack_trace=stack_trace,
                request_method=request_method,
                request_url=request_url,
                query_params=query_params,
                client_ip=client_ip,
                status="open",
            )
            session.add(err_record)
            session.commit()
            error_id = err_record.id
    except Exception as e:
        logger.error(f"Failed to record server error to database: {e}")

    # 2. Append to disk log ~/.kb/logs/server_errors.jsonl
    try:
        log_dir = Path.home() / ".kb" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        jsonl_file = log_dir / "server_errors.jsonl"
        entry = {
            "id": error_id,
            "timestamp": timestamp,
            "error_type": error_type,
            "error_message": error_message,
            "request_method": request_method,
            "request_url": request_url,
            "client_ip": client_ip,
        }
        with open(jsonl_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception as e:
        logger.error(f"Failed to write server error to JSONL disk log: {e}")

    # 3. Post to Gotify channel
    try:
        post_error_to_gotify(config, exc, tb, request, error_id=error_id)
    except Exception as e:
        logger.error(f"Failed to post error to Gotify: {e}")

    # 4. Auto-trigger Maintenance Agent sidecar analysis in background
    if error_id is not None:
        try:
            from .maintenance_agent import dispatch_error_to_maintenance_agent
            dispatch_error_to_maintenance_agent(error_id, background=True)
        except Exception as e:
            logger.error(f"Failed to dispatch error #{error_id} to maintenance agent: {e}")

    return error_id


def post_error_to_gotify(
    config,
    exc: Exception,
    tb: str,
    request: Optional[Request] = None,
    error_id: Optional[int] = None,
) -> None:
    """Sends a formatted Gotify notification detailing an uncaught internal server exception."""
    try:
        notifier = config.get_notifier()
        if not notifier.POST_ENABLED:
            # Gotify is not configured, skip silently
            return

        id_tag = f" [#{error_id}]" if error_id is not None else ""
        title = f"🚨 Server Error: {type(exc).__name__}{id_tag}"

        msg_parts = [
            f"**Error Details:** {str(exc)}",
            "",
        ]

        if request:
            msg_parts.append(f"**Request:** `{request.method} {request.url.path}`")
            if request.query_params:
                msg_parts.append(f"**Query Params:** `{dict(request.query_params)}`")
            client_ip = request.client.host if request.client else "unknown"
            msg_parts.append(f"**Client IP:** `{client_ip}`")
            msg_parts.append("")

        msg_parts.append("**Stack Trace:**")
        msg_parts.append(f"```\n{tb}\n```")

        message = "\n".join(msg_parts)
        notifier.send_notification(title, message)
    except Exception as e:
        print(f"Failed to post traceback error to Gotify channel: {e}")


def post_to_gotify(config, jinja_env, page, view_url: str) -> None:
    """Dispatches Gotify notifications on successful wiki ingestion."""
    try:
        template = jinja_env.get_template("url_import_notification.j2.txt")
        message = template.render({"page": page, "view_url": view_url})
        notifier = config.get_notifier()
        notifier.send_notification("Scraped Wiki Ingestion", message)
    except Exception as e:
        print(f"Failed to post success event to Gotify: {e}")
