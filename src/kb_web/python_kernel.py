"""
Human-in-the-loop (HITL) local Python execution kernel for autonomous custom agents.
All execution in the local .venv is strictly gated behind human review and approval.
"""

from datetime import datetime, timezone
import hashlib
import json
import logging
import os
import secrets
import subprocess
import sys
from typing import Any, Dict, Optional

from .base import db_session, config
from .models_orm import (
    AgentPythonApproval,
    AgentPage,
    IngestionNotification,
    CustomAgent,
)

logger = logging.getLogger(__name__)


def propose_python_execution(
    agent_id: str,
    code: str,
    purpose: str,
    session,
) -> Dict[str, Any]:
    """Registers a pending Python execution request and creates an approval AgentPage with notifications."""
    now_iso = datetime.now(timezone.utc).isoformat()

    approval = AgentPythonApproval(
        agent_id=agent_id,
        code=code.strip(),
        purpose=purpose.strip() or "Autonomous data analysis / calculation",
        status="pending",
        output="",
        created_at=now_iso,
    )
    session.add(approval)
    session.flush()
    session.refresh(approval)

    # Generate a unique hash ID for the approval AgentPage
    token = secrets.token_hex(8)
    hash_id = f"hitl_{approval.id}_{token}"

    form_schema = {
        "approval_id": approval.id,
        "type": "approval_form",
        "action": f"/api/pages/agent/{hash_id}/submit",
        "fields": [
            {
                "name": "decision",
                "label": "Approval Decision",
                "type": "radio",
                "options": ["approve", "reject"],
                "default": "approve",
            },
            {
                "name": "feedback",
                "label": "User Feedback / Guidance (Optional)",
                "type": "textarea",
                "placeholder": "Provide hints, parameter adjustments, or reason if rejected...",
            },
        ],
    }

    markdown_body = f"""### 🛡️ Human-In-The-Loop Python Execution Request

**Agent**: `{agent_id}`  
**Purpose**: {approval.purpose}  
**Requested At**: `{now_iso[:19]}`

```python
{approval.code}
```

> [!CAUTION]
> This code will execute locally using the server Python virtual environment (`.venv`). Review the code carefully before approving.
"""

    agent_page = AgentPage(
        hash_id=hash_id,
        agent_id=agent_id,
        title=f"Python Execution Approval - {approval.purpose[:40]}",
        render_mode="themed",
        body_content=markdown_body,
        form_schema_json=json.dumps(form_schema),
        user_response_json="{}",
        is_temporary=1,
        created_at=now_iso,
    )
    session.add(agent_page)

    # Dispatch ingestion notification to alert user immediately
    notif = IngestionNotification(
        task_id=f"hitl_{approval.id}",
        url=f"/pages/agent/{hash_id}",
        title=f"Approval Needed: Agent {agent_id}",
        stage="agent",
        status="warning",
        message=f"Agent '{agent_id}' requested approval to execute Python code: {approval.purpose[:80]}",
        details=f"approval_id={approval.id}&page_id=/pages/agent/{hash_id}\n\nCode:\n{approval.code[:300]}",
        created_at=now_iso,
        read=0,
    )
    session.add(notif)
    session.flush()

    return {
        "status": "pending_approval",
        "approval_id": approval.id,
        "hash_id": hash_id,
        "approval_url": f"/pages/agent/{hash_id}",
    }


def execute_approved_code(approval_id: int, session, timeout_seconds: int = 30) -> Dict[str, Any]:
    """Executes an approved Python code block within the project's Python environment."""
    approval = session.query(AgentPythonApproval).filter_by(id=approval_id).first()
    if not approval:
        return {"status": "error", "message": f"Approval #{approval_id} not found"}

    if approval.status not in ("pending", "approved"):
        return {"status": "error", "message": f"Approval #{approval_id} is in status '{approval.status}' and cannot be executed."}

    now_iso = datetime.now(timezone.utc).isoformat()
    python_bin = sys.executable

    logger.info(f"Executing approved Python code for approval #{approval_id} using {python_bin}")

    try:
        proc = subprocess.run(
            [python_bin, "-c", approval.code],
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            cwd=str(config.WORKSPACE_ROOT) if hasattr(config, "WORKSPACE_ROOT") else os.getcwd(),
        )
        combined_output = ""
        if proc.stdout:
            combined_output += f"[stdout]\n{proc.stdout}\n"
        if proc.stderr:
            combined_output += f"[stderr]\n{proc.stderr}\n"

        if proc.returncode == 0:
            approval.status = "executed"
        else:
            approval.status = "failed"
            combined_output += f"\n[Process exited with non-zero return code {proc.returncode}]"

        approval.output = combined_output
        approval.executed_at = now_iso
        session.commit()

        return {
            "status": approval.status,
            "returncode": proc.returncode,
            "output": combined_output,
            "executed_at": now_iso,
        }
    except subprocess.TimeoutExpired:
        approval.status = "failed"
        approval.output = f"Execution timed out after {timeout_seconds} seconds."
        approval.executed_at = now_iso
        session.commit()
        return {"status": "timeout", "output": approval.output}
    except Exception as e:
        approval.status = "failed"
        approval.output = f"Execution failed with exception: {e}"
        approval.executed_at = now_iso
        session.commit()
        return {"status": "error", "output": approval.output}


def reject_code_execution(approval_id: int, session, reason: str = "") -> Dict[str, Any]:
    """Marks a pending Python execution request as rejected."""
    approval = session.query(AgentPythonApproval).filter_by(id=approval_id).first()
    if not approval:
        return {"status": "error", "message": f"Approval #{approval_id} not found"}

    approval.status = "rejected"
    approval.output = f"Rejected by user: {reason}" if reason else "Rejected by user."
    session.commit()
    return {"status": "rejected", "approval_id": approval_id}
