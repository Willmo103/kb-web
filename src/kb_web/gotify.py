"""
Gotify error notifications utility for the Knowledge Base Web Importer.
"""

from typing import Optional
from fastapi import Request


def post_error_to_gotify(config, exc: Exception, tb: str, request: Optional[Request] = None) -> None:
    """Sends a formatted Gotify notification detailing an uncaught internal server exception."""
    try:
        notifier = config.get_notifier()
        if not notifier.token or not notifier.url:
            # Gotify is not configured, skip silently
            return

        title = f"🚨 Server Error: {type(exc).__name__}"
        
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

