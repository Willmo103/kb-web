"""
Workspace Coding Agent Tools Primitives.
Provides structured operations (create_file, read_file, edit_file) on workspace files
without requiring entire repository dumping into LLM context.
"""

from datetime import datetime
from typing import Optional, Dict, Any
from sqlalchemy.orm import Session

from .models_orm import Workspace, WorkspaceFile


def _normalize_path(path: str) -> str:
    cleaned = path.replace("\\", "/").strip("/").replace("//", "/")
    parts = cleaned.split("/")
    if ".." in parts or not cleaned:
        raise ValueError(f"Invalid file path or path traversal detected: {path}")
    return cleaned


def tool_create_file(
    session: Session,
    workspace_id: int,
    file_path: str,
    content: str,
    annotation: Optional[str] = None,
    language: Optional[str] = None,
) -> Dict[str, Any]:
    """Creates a new file or overwrites an existing file in the workspace."""
    clean_path = _normalize_path(file_path)
    now_str = datetime.now().isoformat()

    ws = session.query(Workspace).filter_by(id=workspace_id).first()
    if not ws:
        raise ValueError(f"Workspace {workspace_id} not found.")

    existing = (
        session.query(WorkspaceFile)
        .filter_by(workspace_id=workspace_id, file_path=clean_path)
        .first()
    )
    is_new = existing is None
    if existing:
        existing.content = content
        if language:
            existing.language = language
        existing.updated_at = now_str
    else:
        new_file = WorkspaceFile(
            workspace_id=workspace_id,
            file_path=clean_path,
            content=content,
            language=language or "plaintext",
            updated_at=now_str,
        )
        session.add(new_file)

    ws.updated_at = now_str
    session.commit()

    return {
        "success": True,
        "action": "created" if is_new else "updated",
        "file_path": clean_path,
        "annotation": annotation,
        "bytes": len(content),
    }


def tool_read_file(
    session: Session,
    workspace_id: int,
    file_path: str,
    start_line: Optional[int] = None,
    end_line: Optional[int] = None,
) -> Dict[str, Any]:
    """Reads a section or full content of a workspace file using 1-indexed line windows."""
    clean_path = _normalize_path(file_path)

    f = (
        session.query(WorkspaceFile)
        .filter_by(workspace_id=workspace_id, file_path=clean_path)
        .first()
    )
    if not f:
        return {
            "success": False,
            "error": f"File '{clean_path}' not found in workspace {workspace_id}.",
        }

    raw_content = f.content or ""
    lines = raw_content.splitlines(keepends=True)
    total_lines = len(lines)

    if total_lines == 0:
        return {
            "success": True,
            "file_path": clean_path,
            "start_line": 1,
            "end_line": 0,
            "total_lines": 0,
            "content": "",
        }

    s_line = max(1, start_line) if start_line is not None else 1
    e_line = min(total_lines, end_line) if end_line is not None else total_lines

    if s_line > total_lines:
        return {
            "success": False,
            "error": f"start_line {s_line} exceeds total lines ({total_lines}).",
        }

    sliced_lines = lines[s_line - 1 : e_line]
    sliced_content = "".join(sliced_lines)

    return {
        "success": True,
        "file_path": clean_path,
        "start_line": s_line,
        "end_line": e_line,
        "total_lines": total_lines,
        "content": sliced_content,
        "language": f.language,
    }


def tool_edit_file(
    session: Session,
    workspace_id: int,
    file_path: str,
    target_content: str,
    replacement_content: str,
    allow_multiple: bool = False,
) -> Dict[str, Any]:
    """Performs precise search-and-replace modification inside a workspace file."""
    clean_path = _normalize_path(file_path)
    now_str = datetime.now().isoformat()

    ws = session.query(Workspace).filter_by(id=workspace_id).first()
    if not ws:
        return {"success": False, "error": f"Workspace {workspace_id} not found."}

    f = (
        session.query(WorkspaceFile)
        .filter_by(workspace_id=workspace_id, file_path=clean_path)
        .first()
    )
    if not f:
        return {
            "success": False,
            "error": f"File '{clean_path}' not found in workspace {workspace_id}.",
        }

    content = f.content or ""
    count = content.count(target_content)

    if count == 0:
        return {
            "success": False,
            "error": f"Target content not found in '{clean_path}'. Please verify the exact lines.",
        }

    if count > 1 and not allow_multiple:
        return {
            "success": False,
            "error": f"Target content matches {count} occurrences in '{clean_path}'. Provide more context or set allow_multiple=True.",
        }

    new_content = content.replace(target_content, replacement_content)
    f.content = new_content
    f.updated_at = now_str
    ws.updated_at = now_str
    session.commit()

    return {
        "success": True,
        "action": "edited",
        "file_path": clean_path,
        "replacements": count,
        "bytes": len(new_content),
    }
