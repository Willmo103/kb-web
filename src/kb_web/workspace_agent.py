"""
Workspace Coding Agent Engine.
Integrates tev1 structured decision models (via native ollama.systemone) with
workspace agent tool executions (create_file, read_file, edit_file).
"""

import json
import logging
import re
from typing import Optional, Dict, Any, List
from sqlalchemy.orm import Session

from .agent_tools import tool_create_file, tool_read_file, tool_edit_file
from .models_orm import Workspace

logger = logging.getLogger(__name__)


def run_tev1_gating(
    client,
    workspace_files: List[str],
    user_prompt: str,
    active_file: Optional[str] = None,
    tev1_model: str = "tev1",
) -> Dict[str, Any]:
    """Runs fast decision gating using tev1 to classify intent, identify targets, and determine reading needs."""
    files_subset = workspace_files[:12]
    file_choices = {f: f"File: {f}" for f in files_subset}
    file_choices["none"] = "No existing file or a brand new file."

    state = {
        "workspace_files": workspace_files,
        "active_file": active_file or "none",
        "user_prompt": user_prompt,
    }

    questions = {
        "intent": {
            "type": "choice",
            "instructions": "What is the primary action requested in the user prompt?",
            "criteria": {
                "chat": "General question, explanation, or planning with no immediate code change.",
                "read_file": "Needs to inspect or read existing file content before modifying.",
                "create_file": "Needs to create a new file in the workspace.",
                "edit_file": "Needs to modify or edit an existing file in the workspace.",
            },
        },
        "target_file": {
            "type": "choice",
            "instructions": "Which workspace file is the primary target of this action?",
            "criteria": file_choices,
        },
        "needs_reading": {
            "type": "noul",
            "instructions": "Does the agent need to read a file or slice to answer or execute the request?",
            "criteria": {
                "true": "The agent must read file content to proceed.",
                "false": "No reading needed, or content is already known.",
            },
        },
    }

    try:
        resp = client.systemone(
            model=tev1_model,
            state=state,
            questions=questions,
        )
        answers = getattr(resp, "answers", {})
        intent = getattr(answers.get("intent"), "choice", "chat")
        target_file = getattr(answers.get("target_file"), "choice", "none")
        needs_reading_val = getattr(answers.get("needs_reading"), "noul", 0.0)

        return {
            "success": True,
            "intent": intent,
            "target_file": None if target_file == "none" else target_file,
            "needs_reading": bool(needs_reading_val > 0.5),
            "raw": str(answers),
        }
    except Exception as e:
        logger.warning(f"tev1 systemone decision routing failed: {e}. Falling back to default heuristics.")
        # Fallback heuristic
        prompt_lower = user_prompt.lower()
        intent = "chat"
        if "create" in prompt_lower or "add" in prompt_lower:
            intent = "create_file"
        elif "edit" in prompt_lower or "modify" in prompt_lower or "fix" in prompt_lower or "update" in prompt_lower:
            intent = "edit_file"
        elif "read" in prompt_lower or "show" in prompt_lower or "inspect" in prompt_lower:
            intent = "read_file"

        return {
            "success": False,
            "intent": intent,
            "target_file": active_file,
            "needs_reading": intent in ("read_file", "edit_file"),
            "error": str(e),
        }


def execute_agent_step(
    session: Session,
    client,
    workspace_id: int,
    user_prompt: str,
    coding_model: str,
    active_file: Optional[str] = None,
    tev1_model: str = "tev1",
) -> Dict[str, Any]:
    """
    Executes a complete agent step for a workspace:
    1. Gating with tev1 (intent, target file, reading need).
    2. File slice read if needed.
    3. LLM tool dispatch and generation.
    4. Execution of create_file / edit_file operations.
    """
    ws = session.query(Workspace).filter_by(id=workspace_id).first()
    if not ws:
        raise ValueError(f"Workspace {workspace_id} not found.")

    workspace_files = [f.file_path for f in ws.files]

    # Step 1: Decision gating with tev1
    decision = run_tev1_gating(
        client=client,
        workspace_files=workspace_files,
        user_prompt=user_prompt,
        active_file=active_file,
        tev1_model=tev1_model,
    )

    # Step 2: Context gathering via tool_read_file if determined necessary
    context_sections = []
    read_actions = []

    target_for_read = decision.get("target_file") or active_file
    if decision.get("needs_reading") and target_for_read and target_for_read in workspace_files:
        read_res = tool_read_file(session, workspace_id, target_for_read, start_line=1, end_line=200)
        if read_res.get("success"):
            read_actions.append(read_res)
            context_sections.append(
                f"File content for '{target_for_read}' (lines 1-{read_res['end_line']} of {read_res['total_lines']}):\n```\n{read_res['content']}\n```"
            )

    tools_documentation = (
        "Available Tools:\n"
        "1. create_file: Create or replace a file in the workspace.\n"
        "   Syntax:\n"
        "   ```tool:create_file\n"
        '   {"file_path": "path/file.ext", "content": "file contents", "annotation": "Why this file was created"}\n'
        "   ```\n\n"
        "2. edit_file: Modify an existing file with precise search and replace.\n"
        "   Syntax:\n"
        "   ```tool:edit_file\n"
        '   {"file_path": "path/file.ext", "target_content": "exact code to replace", "replacement_content": "new replacement code"}\n'
        "   ```\n\n"
        "3. read_file: Read a slice of a file.\n"
        "   Syntax:\n"
        "   ```tool:read_file\n"
        '   {"file_path": "path/file.ext", "start_line": 1, "end_line": 100}\n'
        "   ```\n\n"
        "4. Standard file block (also accepted):\n"
        "   ```file:path/to/file.ext\n"
        "   <full file content>\n"
        "   ```\n"
    )

    context_str = "\n\n".join(context_sections)
    system_prompt = (
        f"You are an expert autonomous coding agent for workspace '{ws.name}'.\n"
        f"Workspace files: {workspace_files}\n"
        f"Decision triage intent: {decision.get('intent')} (target: {decision.get('target_file')})\n\n"
        f"{context_str}\n\n"
        f"{tools_documentation}\n"
        "Explain your plan concisely, and invoke any needed tools using the code block formats above."
    )

    chat_messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    llm_resp = client.chat(
        model=coding_model,
        messages=chat_messages,
    )

    reply_content = ""
    if hasattr(llm_resp, "message") and hasattr(llm_resp.message, "content"):
        reply_content = llm_resp.message.content
    elif isinstance(llm_resp, dict) and "message" in llm_resp and "content" in llm_resp["message"]:
        reply_content = llm_resp["message"]["content"]
    else:
        reply_content = str(llm_resp)

    # Step 3: Parse and execute tool calls in response
    executed_tools = []

    # Parse ```tool:create_file JSON
    create_pattern = re.compile(r"```tool:create_file\s*\n(.*?)\n```", re.DOTALL)
    for match in create_pattern.finditer(reply_content):
        try:
            data = json.loads(match.group(1).strip())
            res = tool_create_file(
                session,
                workspace_id,
                file_path=data["file_path"],
                content=data["content"],
                annotation=data.get("annotation"),
            )
            executed_tools.append(res)
        except Exception as err:
            logger.warning(f"Error executing create_file tool call: {err}")

    # Parse ```tool:edit_file JSON
    edit_pattern = re.compile(r"```tool:edit_file\s*\n(.*?)\n```", re.DOTALL)
    for match in edit_pattern.finditer(reply_content):
        try:
            data = json.loads(match.group(1).strip())
            res = tool_edit_file(
                session,
                workspace_id,
                file_path=data["file_path"],
                target_content=data["target_content"],
                replacement_content=data["replacement_content"],
                allow_multiple=data.get("allow_multiple", False),
            )
            executed_tools.append(res)
        except Exception as err:
            logger.warning(f"Error executing edit_file tool call: {err}")

    # Parse ```tool:read_file JSON
    read_pattern = re.compile(r"```tool:read_file\s*\n(.*?)\n```", re.DOTALL)
    for match in read_pattern.finditer(reply_content):
        try:
            data = json.loads(match.group(1).strip())
            res = tool_read_file(
                session,
                workspace_id,
                file_path=data["file_path"],
                start_line=data.get("start_line"),
                end_line=data.get("end_line"),
            )
            executed_tools.append(res)
        except Exception as err:
            logger.warning(f"Error executing read_file tool call: {err}")

    # Backward-compatible ```file:path parsing
    file_block_pattern = re.compile(r"```file:([^\n]+)\n(.*?)\n```", re.DOTALL)
    for match in file_block_pattern.finditer(reply_content):
        path = match.group(1).strip()
        code = match.group(2)
        try:
            res = tool_create_file(
                session,
                workspace_id,
                file_path=path,
                content=code,
                annotation="Saved from codeblock",
            )
            executed_tools.append(res)
        except Exception as err:
            logger.warning(f"Error saving file block: {err}")

    return {
        "status": "success",
        "decision": decision,
        "reply": reply_content,
        "read_actions": read_actions,
        "executed_tools": executed_tools,
    }
