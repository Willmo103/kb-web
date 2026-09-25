"""
FastAPI Router for persistent Replit-style coding workspaces, in-browser IDE,
Pyodide WASM Python execution, and ephemeral Ollama coding agent in kb-web.
"""

from datetime import datetime
import io
import json
from typing import Optional, Dict, Any, List
import zipfile

from fastapi import APIRouter, HTTPException, Request, Response, Depends
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from sqlalchemy.orm import Session

from ..base import db_session, config, _jinja_env, COOKIE_NAME, verify_session_token, verify_auth
from ..models_orm import Workspace, WorkspaceFile, SettingOllama
from ..models import (
    WorkspaceCreateRequest,
    WorkspaceUpdateRequest,
    WorkspaceFileUpsertRequest,
    WorkspaceAgentChatRequest,
)
from ..utils import _get_ollama_client, ensure_model_available

router = APIRouter(tags=["Workspaces"])


# Starter Project Templates matching workspace.html
STARTER_TEMPLATES: Dict[str, Dict[str, str]] = {
    "web-game": {
        "index.html": """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Cyber Canvas Arcade</title>
  <link rel="stylesheet" href="style.css">
</head>
<body>
  <div class="game-container">
    <header>
      <h1>NEON BLIP ARCADE</h1>
      <div class="score-board">Score: <span id="score">0</span></div>
    </header>
    <canvas id="gameCanvas" width="400" height="300"></canvas>
    <div class="controls">
      <button id="startBtn">Start / Restart</button>
      <p>Use [Arrow Left] and [Arrow Right] or touch to control paddle!</p>
    </div>
  </div>
  <script src="app.js"></script>
</body>
</html>""",
        "style.css": """body {
  margin: 0;
  background: #0f172a;
  color: #f8fafc;
  font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
  display: flex;
  justify-content: center;
  align-items: center;
  min-height: 100vh;
}

.game-container {
  text-align: center;
  background: #1e293b;
  padding: 24px;
  border-radius: 12px;
  box-shadow: 0 10px 25px rgba(0,0,0,0.5);
  border: 1px solid #334155;
}

h1 {
  margin-top: 0;
  font-size: 1.4rem;
  letter-spacing: 2px;
  color: #38bdf8;
  text-shadow: 0 0 10px rgba(56, 189, 248, 0.5);
}

.score-board {
  font-size: 1.1rem;
  font-weight: bold;
  margin-bottom: 12px;
  color: #a855f7;
}

canvas {
  background: #090d16;
  border: 2px solid #38bdf8;
  border-radius: 8px;
  box-shadow: 0 0 15px rgba(56, 189, 248, 0.2);
  display: block;
  margin: 0 auto;
}

.controls {
  margin-top: 16px;
}

button {
  background: #6366f1;
  color: white;
  border: none;
  padding: 8px 18px;
  border-radius: 6px;
  cursor: pointer;
  font-weight: 600;
  transition: all 0.2s;
}

button:hover {
  background: #4f46e5;
  transform: translateY(-1px);
}

p {
  font-size: 0.8rem;
  color: #94a3b8;
  margin-top: 8px;
}""",
        "app.js": """// Neon Blip Game Logic
const canvas = document.getElementById('gameCanvas');
const ctx = canvas.getContext('2d');
const scoreEl = document.getElementById('score');
const startBtn = document.getElementById('startBtn');

let score = 0;
let isPlaying = false;
let animationId;

const paddle = {
  width: 75,
  height: 10,
  x: (canvas.width - 75) / 2,
  speed: 6,
  dx: 0
};

const ball = {
  x: canvas.width / 2,
  y: canvas.height - 30,
  radius: 6,
  dx: 3,
  dy: -3
};

function drawPaddle() {
  ctx.fillStyle = '#38bdf8';
  ctx.shadowColor = '#38bdf8';
  ctx.shadowBlur = 8;
  ctx.fillRect(paddle.x, canvas.height - paddle.height - 5, paddle.width, paddle.height);
  ctx.shadowBlur = 0;
}

function drawBall() {
  ctx.beginPath();
  ctx.arc(ball.x, ball.y, ball.radius, 0, Math.PI * 2);
  ctx.fillStyle = '#a855f7';
  ctx.shadowColor = '#a855f7';
  ctx.shadowBlur = 10;
  ctx.fill();
  ctx.closePath();
  ctx.shadowBlur = 0;
}

function update() {
  if (!isPlaying) return;

  // Move paddle
  paddle.x += paddle.dx;
  if (paddle.x < 0) paddle.x = 0;
  if (paddle.x + paddle.width > canvas.width) paddle.x = canvas.width - paddle.width;

  // Move ball
  ball.x += ball.dx;
  ball.y += ball.dy;

  // Wall collisions
  if (ball.x + ball.radius > canvas.width || ball.x - ball.radius < 0) {
    ball.dx = -ball.dx;
  }
  if (ball.y - ball.radius < 0) {
    ball.dy = -ball.dy;
  }

  // Paddle collision
  if (
    ball.y + ball.radius >= canvas.height - paddle.height - 5 &&
    ball.x >= paddle.x &&
    ball.x <= paddle.x + paddle.width
  ) {
    ball.dy = -ball.dy * 1.05; // speed up slightly
    score += 10;
    scoreEl.innerText = score;
    console.log("Paddle hit! Current score:", score);
  }

  // Game over floor collision
  if (ball.y + ball.radius > canvas.height) {
    isPlaying = false;
    console.warn("Game Over! Final score:", score);
    startBtn.innerText = "Play Again";
  }

  ctx.clearRect(0, 0, canvas.width, canvas.height);
  drawPaddle();
  drawBall();

  if (isPlaying) {
    animationId = requestAnimationFrame(update);
  }
}

function resetGame() {
  score = 0;
  scoreEl.innerText = score;
  paddle.x = (canvas.width - paddle.width) / 2;
  ball.x = canvas.width / 2;
  ball.y = canvas.height - 30;
  ball.dx = 3 * (Math.random() > 0.5 ? 1 : -1);
  ball.dy = -3;
  isPlaying = true;
  cancelAnimationFrame(animationId);
  update();
}

startBtn.addEventListener('click', resetGame);

window.addEventListener('keydown', (e) => {
  if (e.key === 'ArrowRight' || e.key === 'd') paddle.dx = paddle.speed;
  if (e.key === 'ArrowLeft' || e.key === 'a') paddle.dx = -paddle.speed;
});

window.addEventListener('keyup', (e) => {
  if (['ArrowRight', 'ArrowLeft', 'a', 'd'].includes(e.key)) paddle.dx = 0;
});

drawPaddle();
drawBall();
console.log("Arcade Game Initialized. Press Start!");""",
        "README.md": """# Mini Arcade Project

A responsive Neon Arcade canvas game built with pure HTML, CSS, and Vanilla JavaScript.

### How to run:
1. Click the **Run** button at the top header to preview in live sandbox!
2. Use Left and Right Arrow keys to bounce the ball.
3. Use the **Ollama AI Agent** tab to customize paddle size, colors, or add powerups!""",
    },
    "python-demo": {
        "main.py": """# In-Browser Python Execution with Pyodide (WASM)
import math
import sys

def sieve_of_eratosthenes(limit):
    \"\"\"Generate prime numbers up to limit.\"\"\"
    primes = []
    is_prime = [True] * (limit + 1)
    for p in range(2, limit + 1):
        if is_prime[p]:
            primes.append(p)
            for i in range(p * p, limit + 1, p):
                is_prime[i] = False
    return primes

def fibonacci(n):
    a, b = 0, 1
    seq = []
    for _ in range(n):
        seq.append(a)
        a, b = b, a + b
    return seq

print("=" * 45)
print("Welcome to Python WASM Studio!")
print(f"Python Version: {sys.version.split()[0]}")
print("=" * 45)

print("\\n[1] Calculating first 15 Fibonacci numbers:")
print(fibonacci(15))

print("\\n[2] Calculating prime numbers up to 100:")
primes = sieve_of_eratosthenes(100)
print(f"Found {len(primes)} primes: {primes}")

print("\\n[3] Trigonometric table sample:")
for deg in [0, 30, 45, 60, 90]:
    rad = math.radians(deg)
    print(f"  {deg:2d} deg -> sin: {math.sin(rad):.4f}, cos: {math.cos(rad):.4f}")

print("\\nExecution finished successfully!")""",
        "data_utils.py": """# Helper module for calculations
def summarize(numbers):
    if not numbers:
        return {}
    return {
        "count": len(numbers),
        "min": min(numbers),
        "max": max(numbers),
        "average": sum(numbers) / len(numbers)
    }""",
        "README.md": """# Python WASM In-Browser Studio

This template executes full real Python 3 via **Pyodide** WebAssembly directly inside your browser tab!

### Instructions:
- Open `main.py` and click **Run**.
- Standard outputs and errors are rendered live in the Python console.""",
    },
    "blank": {
        "index.html": """<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>New Project</title>
</head>
<body>
  <h1>Hello from Browser IDE!</h1>
</body>
</html>""",
        "README.md": """# New Project
Start creating files and building your project.""",
    },
}


def _infer_language(ext: str) -> str:
    ext = ext.lower().strip(".")
    mapping = {
        "html": "html",
        "htm": "html",
        "css": "css",
        "js": "javascript",
        "jsx": "javascript",
        "mjs": "javascript",
        "ts": "typescript",
        "tsx": "typescript",
        "py": "python",
        "json": "json",
        "md": "markdown",
        "markdown": "markdown",
        "sql": "sql",
        "rs": "rust",
        "sh": "shell",
        "bash": "shell",
        "yaml": "yaml",
        "yml": "yaml",
    }
    return mapping.get(ext, "plaintext")


# -----------------------------------------------------------------------------
# Web UI Pages
# -----------------------------------------------------------------------------

@router.get("/workspaces", response_class=HTMLResponse)
def list_workspaces_ui(request: Request):
    """Renders dashboard listing all persistent coding workspaces."""
    token = request.cookies.get(COOKIE_NAME)
    is_admin = bool(token and verify_session_token(token))

    with db_session() as session:
        workspaces = session.query(Workspace).order_by(Workspace.updated_at.desc()).all()
        # Pre-calculate counts while inside session
        workspaces_data = []
        for w in workspaces:
            workspaces_data.append({
                "id": w.id,
                "name": w.name,
                "description": w.description,
                "template": w.template,
                "files_count": len(w.files),
                "created_at": w.created_at,
                "updated_at": w.updated_at,
            })

    template = _jinja_env.get_template("workspaces_list.j2.html")
    return HTMLResponse(content=template.render(
        workspaces=workspaces_data,
        is_admin=is_admin,
    ))


@router.get("/workspaces/{workspace_id}", response_class=HTMLResponse)
@router.get("/workspace", response_class=HTMLResponse)
def view_workspace_ide(request: Request, workspace_id: Optional[int] = None, id: Optional[int] = None):
    """Renders the full-featured in-browser Monaco IDE Studio for a workspace."""
    target_id = workspace_id or id
    token = request.cookies.get(COOKIE_NAME)
    is_admin = bool(token and verify_session_token(token))

    with db_session() as session:
        if target_id is not None:
            ws = session.query(Workspace).filter_by(id=target_id).first()
        else:
            ws = session.query(Workspace).order_by(Workspace.updated_at.desc()).first()

        if not ws:
            # Seed a default workspace if none exists
            now_str = datetime.now().isoformat()
            ws = Workspace(
                name="Cyber Canvas Arcade",
                description="Interactive HTML5 canvas arcade game starter",
                template="web-game",
                created_at=now_str,
                updated_at=now_str,
            )
            session.add(ws)
            session.commit()
            session.refresh(ws)

            # Seed files
            for path, code in STARTER_TEMPLATES["web-game"].items():
                session.add(WorkspaceFile(
                    workspace_id=ws.id,
                    file_path=path,
                    content=code,
                    language=_infer_language(path),
                    updated_at=now_str,
                ))
            session.commit()
            session.refresh(ws)

        ws_data = {
            "id": ws.id,
            "name": ws.name,
            "description": ws.description,
            "template": ws.template,
            "files": {
                f.file_path: {
                    "content": f.content,
                    "language": f.language or _infer_language(f.file_path),
                }
                for f in ws.files
            },
        }

    template = _jinja_env.get_template("workspace_ide.j2.html")
    return HTMLResponse(content=template.render(
        workspace=ws_data,
        is_admin=is_admin,
        ollama_model=getattr(config, "ollama_model", "ornith:9b"),
        ollama_host=getattr(config, "ollama_host", "http://localhost:11434"),
    ))


# -----------------------------------------------------------------------------
# REST API Endpoints
# -----------------------------------------------------------------------------

@router.get("/api/workspaces")
def list_workspaces_api() -> Dict[str, Any]:
    """Returns JSON list of all persistent workspaces with file count."""
    with db_session() as session:
        workspaces = session.query(Workspace).order_by(Workspace.updated_at.desc()).all()
        return {
            "workspaces": [
                {
                    "id": w.id,
                    "name": w.name,
                    "description": w.description,
                    "template": w.template,
                    "files_count": len(w.files),
                    "created_at": w.created_at,
                    "updated_at": w.updated_at,
                }
                for w in workspaces
            ]
        }


@router.post("/api/workspaces")
def create_workspace_api(payload: WorkspaceCreateRequest) -> Dict[str, Any]:
    """Creates a new persistent workspace populated with starter template files."""
    now_str = datetime.now().isoformat()
    template_key = payload.template if payload.template in STARTER_TEMPLATES else "web-game"

    with db_session() as session:
        ws = Workspace(
            name=payload.name.strip() or "Untitled Workspace",
            description=payload.description or "",
            template=template_key,
            created_at=now_str,
            updated_at=now_str,
        )
        session.add(ws)
        session.commit()
        session.refresh(ws)

        # Seed files from template
        template_files = STARTER_TEMPLATES.get(template_key, STARTER_TEMPLATES["blank"])
        for path, content in template_files.items():
            session.add(WorkspaceFile(
                workspace_id=ws.id,
                file_path=path,
                content=content,
                language=_infer_language(path),
                updated_at=now_str,
            ))
        session.commit()

        return {
            "status": "created",
            "id": ws.id,
            "name": ws.name,
            "template": ws.template,
        }


@router.get("/api/workspaces/{workspace_id}")
def get_workspace_detail_api(workspace_id: int) -> Dict[str, Any]:
    """Returns workspace metadata and complete file contents for IDE loading."""
    with db_session() as session:
        ws = session.query(Workspace).filter_by(id=workspace_id).first()
        if not ws:
            raise HTTPException(status_code=404, detail="Workspace not found")

        files_map = {
            f.file_path: {
                "content": f.content,
                "language": f.language or _infer_language(f.file_path),
            }
            for f in ws.files
        }

        return {
            "id": ws.id,
            "name": ws.name,
            "description": ws.description,
            "template": ws.template,
            "created_at": ws.created_at,
            "updated_at": ws.updated_at,
            "files": files_map,
        }


@router.put("/api/workspaces/{workspace_id}")
def update_workspace_api(workspace_id: int, payload: WorkspaceUpdateRequest) -> Dict[str, Any]:
    """Updates workspace title or description."""
    with db_session() as session:
        ws = session.query(Workspace).filter_by(id=workspace_id).first()
        if not ws:
            raise HTTPException(status_code=404, detail="Workspace not found")

        if payload.name is not None:
            ws.name = payload.name.strip()
        if payload.description is not None:
            ws.description = payload.description.strip()
        ws.updated_at = datetime.now().isoformat()
        session.commit()

        return {"status": "success", "id": ws.id, "name": ws.name}


@router.delete("/api/workspaces/{workspace_id}")
def delete_workspace_api(workspace_id: int) -> Dict[str, Any]:
    """Permanently deletes a workspace and all its files."""
    with db_session() as session:
        ws = session.query(Workspace).filter_by(id=workspace_id).first()
        if not ws:
            raise HTTPException(status_code=404, detail="Workspace not found")
        session.delete(ws)
        session.commit()
        return {"status": "deleted", "id": workspace_id}


@router.post("/api/workspaces/{workspace_id}/duplicate")
def duplicate_workspace_api(workspace_id: int) -> Dict[str, Any]:
    """Duplicates an existing workspace and all its files."""
    now_str = datetime.now().isoformat()
    with db_session() as session:
        ws = session.query(Workspace).filter_by(id=workspace_id).first()
        if not ws:
            raise HTTPException(status_code=404, detail="Workspace not found")

        new_ws = Workspace(
            name=f"{ws.name} (Copy)",
            description=ws.description,
            template=ws.template,
            created_at=now_str,
            updated_at=now_str,
        )
        session.add(new_ws)
        session.commit()
        session.refresh(new_ws)

        for f in ws.files:
            session.add(WorkspaceFile(
                workspace_id=new_ws.id,
                file_path=f.file_path,
                content=f.content,
                language=f.language,
                updated_at=now_str,
            ))
        session.commit()

        return {"status": "duplicated", "id": new_ws.id, "name": new_ws.name}


@router.post("/api/workspaces/{workspace_id}/files")
def upsert_workspace_file_api(workspace_id: int, payload: WorkspaceFileUpsertRequest) -> Dict[str, Any]:
    """Creates or updates a file inside a persistent workspace."""
    clean_path = payload.path.replace("\\", "/").strip("/").replace("//", "/")
    if not clean_path:
        raise HTTPException(status_code=400, detail="Invalid file path")

    now_str = datetime.now().isoformat()
    with db_session() as session:
        ws = session.query(Workspace).filter_by(id=workspace_id).first()
        if not ws:
            raise HTTPException(status_code=404, detail="Workspace not found")

        file_obj = (
            session.query(WorkspaceFile)
            .filter_by(workspace_id=workspace_id, file_path=clean_path)
            .first()
        )
        lang = payload.language or _infer_language(clean_path)

        if file_obj:
            file_obj.content = payload.content
            file_obj.language = lang
            file_obj.updated_at = now_str
        else:
            file_obj = WorkspaceFile(
                workspace_id=workspace_id,
                file_path=clean_path,
                content=payload.content,
                language=lang,
                updated_at=now_str,
            )
            session.add(file_obj)

        ws.updated_at = now_str
        session.commit()

        return {
            "status": "saved",
            "file_path": clean_path,
            "language": lang,
            "updated_at": now_str,
        }


@router.delete("/api/workspaces/{workspace_id}/files")
def delete_workspace_file_api(workspace_id: int, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Deletes a file or directory prefix from a persistent workspace."""
    target_path = payload.get("path", "").replace("\\", "/").strip("/").replace("//", "/")
    if not target_path:
        raise HTTPException(status_code=400, detail="File path required")

    with db_session() as session:
        ws = session.query(Workspace).filter_by(id=workspace_id).first()
        if not ws:
            raise HTTPException(status_code=404, detail="Workspace not found")

        # Delete single file or all files with folder prefix
        deleted_count = 0
        exact_match = (
            session.query(WorkspaceFile)
            .filter_by(workspace_id=workspace_id, file_path=target_path)
            .first()
        )
        if exact_match:
            session.delete(exact_match)
            deleted_count += 1
        else:
            folder_prefix = target_path + "/"
            folder_matches = (
                session.query(WorkspaceFile)
                .filter(
                    WorkspaceFile.workspace_id == workspace_id,
                    WorkspaceFile.file_path.startswith(folder_prefix),
                )
                .all()
            )
            for f in folder_matches:
                session.delete(f)
                deleted_count += 1

        ws.updated_at = datetime.now().isoformat()
        session.commit()

        return {"status": "deleted", "path": target_path, "deleted_count": deleted_count}


@router.get("/api/workspaces/{workspace_id}/export-zip")
@router.post("/api/workspaces/{workspace_id}/export-zip")
def export_workspace_zip_api(workspace_id: int):
    """Exports all workspace files into a downloadable ZIP archive."""
    with db_session() as session:
        ws = session.query(Workspace).filter_by(id=workspace_id).first()
        if not ws:
            raise HTTPException(status_code=404, detail="Workspace not found")

        zip_buf = io.BytesIO()
        with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for f in ws.files:
                zf.writestr(f.file_path, f.content or "")

        zip_buf.seek(0)
        clean_name = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in ws.name)
        filename = f"{clean_name}_workspace.zip"

        return StreamingResponse(
            zip_buf,
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )


@router.post("/api/workspaces/{workspace_id}/agent/chat")
def workspace_agent_chat_api(workspace_id: int, payload: WorkspaceAgentChatRequest) -> Dict[str, Any]:
    """
    Ephemeral coding agent endpoint: takes a user prompt, supplies workspace file tree
    and active file context, and calls Ollama to propose code diffs wrapped in ```file:path blocks.
    """
    user_prompt = payload.message.strip()
    if not user_prompt:
        raise HTTPException(status_code=400, detail="Prompt is required")

    model_name = payload.model or getattr(config, "ollama_model", "ornith:9b")

    with db_session() as session:
        ws = session.query(Workspace).filter_by(id=workspace_id).first()
        if not ws:
            raise HTTPException(status_code=404, detail="Workspace not found")

        paths_list = [f.file_path for f in ws.files]
        active_context = ""
        if payload.active_file:
            active_file_obj = next((f for f in ws.files if f.file_path == payload.active_file), None)
            if active_file_obj:
                active_context = f"\nCurrently open file ({payload.active_file}):\n```\n{active_file_obj.content}\n```"

    system_prompt = (
        f"You are an expert autonomous coding agent operating inside a browser-based IDE workspace.\n"
        f"Workspace files: [{', '.join(paths_list)}].{active_context}\n\n"
        f"When you want to create or edit files in the workspace, you MUST output the complete updated or new file wrapped in this exact syntax:\n"
        f"```file:path/to/filename.ext\n<complete code of file here>\n```\n\n"
        f"Give concise explanations and apply clean, robust, and modern programming patterns."
    )

    client = _get_ollama_client()
    try:
        resp = client.generate(
            model=model_name,
            prompt=f"{system_prompt}\n\nUser Request: {user_prompt}",
            options={"temperature": 0.3},
        )
        reply_text = resp.get("response", "")
        return {
            "status": "success",
            "reply": reply_text,
            "model": model_name,
        }
    except Exception as e:
        # Fallback to smart simulated response if Ollama is unreachable
        return {
            "status": "mock",
            "reply": (
                f"Note: Ollama server connection was unavailable ({str(e)}).\n\n"
                f"Simulated suggestion for '{user_prompt}':\n\n"
                f"```file:app.js\n// Generated sample by AI Agent\nconsole.log('Update applied successfully!');\n```\n"
                f"You can review or apply this change."
            ),
            "model": "simulated-agent",
        }
