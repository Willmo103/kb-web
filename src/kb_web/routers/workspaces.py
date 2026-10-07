"""
FastAPI Router for persistent Replit-style coding workspaces, in-browser IDE,
Pyodide WASM Python execution, and ephemeral Ollama coding agent in kb-web.
"""

from datetime import datetime
import io
import json
import logging
import re
from typing import Optional, Dict, Any, List
import zipfile

import httpx

logger = logging.getLogger(__name__)

from fastapi import APIRouter, HTTPException, Request, Response, Depends
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from sqlalchemy.orm import Session

from ..base import db_session, config, _jinja_env, COOKIE_NAME, verify_session_token, verify_auth
from ..models_orm import Workspace, WorkspaceFile, WorkspaceSnapshot, SettingOllama, FetchedPage
from ..models import (
    WorkspaceCreateRequest,
    WorkspaceUpdateRequest,
    WorkspaceFileUpsertRequest,
    WorkspaceAgentChatRequest,
    WorkspaceSnapshotCreateRequest,
)
from ..utils import _get_ollama_client, ensure_model_available
from ..workspace_agent import execute_agent_step

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

## How to Run

1. Click the **Run** button in the top navigation bar to preview in the live sandbox!
2. Use Left and Right Arrow keys (or A/D) to control the paddle and bounce the ball.
3. Use the **AI Assistant** tab to customize paddle size, colors, or add powerups!
""",
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

This project executes real Python 3 code via **Pyodide** WebAssembly directly inside your browser!

## How to Run

1. Open `main.py` in the Monaco editor.
2. Click the **Run** button in the top navigation bar.
3. Standard outputs and calculation logs appear in real-time in the Python console below.
""",
    },
    "blank": {
        "index.html": """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>New Project</title>
</head>
<body>
  <h1>Hello from Browser IDE!</h1>
  <p>Start creating files and building your project.</p>
</body>
</html>""",
        "README.md": """# New Project

Welcome to your new in-browser coding workspace.

## Getting Started

- Use the **+** button in the Files sidebar to add HTML, CSS, JavaScript, Python, or Markdown files.
- Click **Run** to execute Python scripts, launch the web preview, or render Markdown.
- Collaborate with the integrated Ollama coding assistant.
""",
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


def _generate_workspace_from_prompt(prompt: str, template_hint: Optional[str] = None) -> Dict[str, Any]:
    """Generates project title, type, and starter files from an AI prompt."""
    client = _get_ollama_client()
    model = getattr(config, "ollama_model", "gemma4:latest")

    sys_prompt = (
        "You are an expert full-stack developer and software architect. "
        "A user wants to create a new coding project with the following requirements:\n"
        f"\"{prompt}\"\n\n"
        "Generate a complete starter project. Your response MUST be a valid JSON object with:\n"
        "- \"name\": A concise, professional project name (2-5 words).\n"
        "- \"template\": The project type/language (e.g. 'web-game', 'python-demo', 'markdown', 'gist', 'react', 'cli', etc.).\n"
        "- \"description\": A brief 1-2 sentence description of what the project does.\n"
        "- \"files\": An object mapping relative file paths to their complete, working code contents.\n"
        "  You MUST include a clean, comprehensive 'README.md' explaining the project, file structure, and how to run or use it.\n"
        "Format: Return ONLY the JSON object without markdown fences or filler text."
    )

    try:
        resp = client.chat(
            model=model,
            messages=[{"role": "user", "content": sys_prompt}],
            options={"temperature": 0.3, "num_predict": 2048},
        )
        raw = resp["message"]["content"].strip()
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            data = json.loads(match.group(0))
            raw_files = data.get("files")
            files = {}
            if isinstance(raw_files, list):
                for item in raw_files:
                    if isinstance(item, dict):
                        p = item.get("path") or item.get("name") or item.get("file")
                        c = item.get("content", "")
                        if p:
                            files[str(p)] = str(c)
            elif isinstance(raw_files, dict):
                files = {str(k): str(v) for k, v in raw_files.items()}

            if files:
                name = str(data.get("name") or data.get("project_name", "")).strip() or "AI Generated Project"
                desc = str(data.get("description", "")).strip() or f"Project created from prompt: {prompt[:80]}"
                tmpl = str(data.get("template", template_hint or "custom")).strip().lower()
                if "README.md" not in files:
                    files["README.md"] = f"# {name}\n\n{desc}\n\n### Overview\nGenerated by AI assistant for: *{prompt}*.\n"
                return {
                    "name": name,
                    "description": desc,
                    "template": tmpl,
                    "files": files,
                }
    except Exception as e:
        logger.warning(f"AI workspace generation fallback: {e}")

    # Heuristic fallback if Ollama fails or is unreachable
    clean_p = prompt.strip()
    is_py = any(k in clean_p.lower() for k in ["python", "py", "script", "algorithm", "data", "pandas"])
    is_web = any(k in clean_p.lower() for k in ["game", "html", "css", "canvas", "web", "dom", "ui", "page"])

    derived_name = clean_p[:40].title() if len(clean_p) > 5 else "AI Workspace"
    derived_name = re.sub(r"[^\w\s-]", "", derived_name).strip() or "New Project"

    if template_hint and template_hint not in ("web-game", "blank", "custom"):
        tmpl = template_hint
        files = {
            "README.md": f"# {derived_name}\n\n{clean_p}\n\n## Project Notes\n\nThis is a multi-file workspace created for: *{clean_p}*.\n\n- Add any files or code modules using the New File button.\n",
            "notes.md": f"# Notes: {derived_name}\n\n- Objective: {clean_p}\n- Template: {tmpl}\n",
        }
    elif is_py:
        tmpl = "python-demo"
        files = {
            "main.py": f"# {derived_name}\n# Generated for prompt: {clean_p}\n\ndef main():\n    print(\"Hello from {derived_name}!\")\n\nif __name__ == '__main__':\n    main()\n",
            "README.md": f"# {derived_name}\n\n{clean_p}\n\n## Getting Started\n\n1. Open `main.py` in the Monaco editor.\n2. Click the **Run** button to execute using in-browser Pyodide WASM!\n",
        }
    elif is_web:
        tmpl = "web-game"
        files = {
            "index.html": f"<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n  <meta charset=\"UTF-8\">\n  <title>{derived_name}</title>\n  <link rel=\"stylesheet\" href=\"style.css\">\n</head>\n<body>\n  <h1>{derived_name}</h1>\n  <p>{clean_p}</p>\n  <script src=\"app.js\"></script>\n</body>\n</html>",
            "style.css": "body {\n  font-family: sans-serif;\n  background: #0f172a;\n  color: #f8fafc;\n  padding: 24px;\n}\n",
            "app.js": f"console.log('{derived_name} loaded');\n",
            "README.md": f"# {derived_name}\n\n{clean_p}\n\n## Getting Started\n\n1. Click the **Run** button to launch the live web sandbox preview.\n2. Edit `index.html`, `style.css`, or `app.js` to customize.\n",
        }
    else:
        tmpl = template_hint or "gist"
        files = {
            "README.md": f"# {derived_name}\n\n{clean_p}\n\n## Project Notes\n\nThis is a multi-file workspace created for: *{clean_p}*.\n\n- Add any files or code modules using the New File button.\n- Use the AI Assistant tab to collaborate on code.\n",
            "notes.md": f"# Notes: {derived_name}\n\n- Objective: {clean_p}\n",
        }

    return {
        "name": derived_name,
        "description": f"Generated from prompt: {clean_p[:120]}",
        "template": tmpl,
        "files": files,
    }


@router.post("/api/workspaces")
def create_workspace_api(payload: WorkspaceCreateRequest) -> Dict[str, Any]:
    """Creates a new persistent workspace populated with starter template files or AI-generated files."""
    now_str = datetime.now().isoformat()

    ws_name = (payload.name or "").strip()
    ws_desc = (payload.description or "").strip()
    template_key = (payload.template or "web-game").strip()
    files_to_seed = {}

    if payload.prompt and payload.prompt.strip():
        ai_res = _generate_workspace_from_prompt(payload.prompt.strip(), template_hint=template_key)
        if not ws_name or ws_name == "Untitled Workspace":
            ws_name = ai_res["name"]
        if not ws_desc:
            ws_desc = ai_res["description"]
        template_key = ai_res["template"]
        files_to_seed = ai_res["files"]
    elif template_key in STARTER_TEMPLATES:
        files_to_seed = STARTER_TEMPLATES[template_key]
    else:
        # Custom/Arbitrary Project Type (Gist Mode)
        files_to_seed = {
            "README.md": f"# {ws_name or 'Custom Workspace'}\n\n{ws_desc or 'Multi-file workspace.'}\n\n### Project Type: {template_key}\n\n- Add, edit, and organize files in the explorer tree.\n- Click **Run** to execute supported files (Python WASM, Web Preview, Markdown Preview).\n",
            "notes.md": f"# {ws_name or 'Project'} Notes\n\n- Project Type: {template_key}\n- Created: {now_str}\n",
        }

    if not ws_name:
        ws_name = "Untitled Workspace"

    with db_session() as session:
        ws = Workspace(
            name=ws_name,
            description=ws_desc,
            template=template_key,
            created_at=now_str,
            updated_at=now_str,
        )
        session.add(ws)
        session.commit()
        session.refresh(ws)

        # Seed files
        for path, content in files_to_seed.items():
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


@router.get("/api/models")
@router.get("/api/workspaces/models")
@router.get("/api/workspaces/tags")
def list_workspace_models() -> Dict[str, Any]:
    """
    Returns available Ollama models dynamically pulled from Ollama's tags endpoint,
    as well as models currently loaded in VRAM from Ollama's /api/ps endpoint.
    """
    client = _get_ollama_client()
    models: List[str] = []
    loaded_models: List[str] = []
    default_model = getattr(config, "ollama_model", "gemma4:latest")

    # 1. Fetch installed models from /api/tags
    try:
        models_resp = client.list()
        raw_models = getattr(models_resp, "models", None)
        if raw_models is None and isinstance(models_resp, dict):
            raw_models = models_resp.get("models", [])
        raw_models = raw_models or []

        for m in raw_models:
            name = None
            if hasattr(m, "model") and m.model:
                name = m.model
            elif hasattr(m, "name") and m.name:
                name = m.name
            elif isinstance(m, dict):
                name = m.get("model") or m.get("name")
            if name and name not in models:
                models.append(name)
    except Exception as e:
        logger.warning(f"Error fetching Ollama models: {e}")

    # 2. Fetch loaded models from /api/ps
    try:
        ollama_host = getattr(config, "ollama_host", "http://localhost:11434").rstrip("/")
        with httpx.Client(timeout=2.5) as hclient:
            ps_resp = hclient.get(f"{ollama_host}/api/ps")
            if ps_resp.status_code == 200:
                ps_data = ps_resp.json()
                for m in ps_data.get("models", []):
                    name = m.get("model") or m.get("name")
                    if name and name not in loaded_models:
                        loaded_models.append(name)
    except Exception as e:
        logger.debug(f"Could not query Ollama /api/ps: {e}")

    if not models and default_model:
        models.append(default_model)

    return {
        "status": "success",
        "models": models,
        "loaded_models": loaded_models,
        "default_model": default_model if default_model in models else (models[0] if models else default_model),
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
    if not clean_path or ".." in clean_path.split("/"):
        raise HTTPException(status_code=400, detail="Invalid file path: directory traversal not permitted.")

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
    if not target_path or ".." in target_path.split("/"):
        raise HTTPException(status_code=400, detail="File path required and directory traversal not permitted.")

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


@router.post("/api/workspaces/{workspace_id}/snapshots")
def create_workspace_snapshot_api(
    workspace_id: int, payload: WorkspaceSnapshotCreateRequest
) -> Dict[str, Any]:
    """Creates a tagged, immutable snapshot of the current workspace file tree."""
    tag = payload.version_tag.strip()
    if not tag:
        raise HTTPException(status_code=400, detail="Version tag is required.")

    with db_session() as session:
        ws = session.query(Workspace).filter_by(id=workspace_id).first()
        if not ws:
            raise HTTPException(status_code=404, detail="Workspace not found")

        existing = (
            session.query(WorkspaceSnapshot)
            .filter_by(workspace_id=workspace_id, version_tag=tag)
            .first()
        )
        if existing:
            raise HTTPException(
                status_code=400,
                detail=f"Snapshot with tag '{tag}' already exists.",
            )

        files_map = {
            f.file_path: {
                "content": f.content,
                "language": f.language or _infer_language(f.file_path),
            }
            for f in ws.files
        }

        now_str = datetime.now().isoformat()
        snapshot = WorkspaceSnapshot(
            workspace_id=workspace_id,
            version_tag=tag,
            description=payload.description or "",
            files_snapshot=json.dumps(files_map),
            is_frozen=1,
            created_at=now_str,
        )
        session.add(snapshot)
        session.commit()

        return {
            "status": "success",
            "snapshot_id": snapshot.id,
            "version_tag": snapshot.version_tag,
            "file_count": len(files_map),
            "created_at": snapshot.created_at,
        }


@router.get("/api/workspaces/{workspace_id}/snapshots")
def list_workspace_snapshots_api(workspace_id: int) -> List[Dict[str, Any]]:
    """Lists all tagged snapshots for a workspace."""
    with db_session() as session:
        ws = session.query(Workspace).filter_by(id=workspace_id).first()
        if not ws:
            raise HTTPException(status_code=404, detail="Workspace not found")

        snapshots = (
            session.query(WorkspaceSnapshot)
            .filter_by(workspace_id=workspace_id)
            .order_by(WorkspaceSnapshot.id.desc())
            .all()
        )
        res = []
        for s in snapshots:
            try:
                files_map = json.loads(s.files_snapshot or "{}")
                count = len(files_map)
            except Exception:
                count = 0
            res.append(
                {
                    "id": s.id,
                    "version_tag": s.version_tag,
                    "description": s.description,
                    "file_count": count,
                    "is_frozen": bool(s.is_frozen),
                    "created_at": s.created_at,
                }
            )
        return res


@router.get("/api/workspaces/{workspace_id}/snapshots/{snapshot_id}")
def get_workspace_snapshot_detail_api(
    workspace_id: int, snapshot_id: int
) -> Dict[str, Any]:
    """Retrieves full details and file map for a specific workspace snapshot."""
    with db_session() as session:
        snapshot = (
            session.query(WorkspaceSnapshot)
            .filter_by(workspace_id=workspace_id, id=snapshot_id)
            .first()
        )
        if not snapshot:
            raise HTTPException(status_code=404, detail="Snapshot not found")

        return {
            "id": snapshot.id,
            "workspace_id": snapshot.workspace_id,
            "version_tag": snapshot.version_tag,
            "description": snapshot.description,
            "is_frozen": bool(snapshot.is_frozen),
            "created_at": snapshot.created_at,
            "files": json.loads(snapshot.files_snapshot or "{}"),
        }


@router.post("/api/workspaces/{workspace_id}/snapshots/{snapshot_id}/restore")
def restore_workspace_snapshot_api(
    workspace_id: int, snapshot_id: int
) -> Dict[str, Any]:
    """Restores the workspace file tree from a frozen snapshot."""
    with db_session() as session:
        ws = session.query(Workspace).filter_by(id=workspace_id).first()
        if not ws:
            raise HTTPException(status_code=404, detail="Workspace not found")

        snapshot = (
            session.query(WorkspaceSnapshot)
            .filter_by(workspace_id=workspace_id, id=snapshot_id)
            .first()
        )
        if not snapshot:
            raise HTTPException(status_code=404, detail="Snapshot not found")

        files_map = json.loads(snapshot.files_snapshot or "{}")
        now_str = datetime.now().isoformat()

        # Delete existing files
        for f in list(ws.files):
            session.delete(f)

        # Restore files from snapshot
        for path, info in files_map.items():
            session.add(
                WorkspaceFile(
                    workspace_id=workspace_id,
                    file_path=path,
                    content=info.get("content", ""),
                    language=info.get("language") or _infer_language(path),
                    updated_at=now_str,
                )
            )

        ws.updated_at = now_str
        session.commit()

        return {
            "status": "restored",
            "workspace_id": workspace_id,
            "version_tag": snapshot.version_tag,
            "restored_file_count": len(files_map),
        }


@router.post(
    "/api/workspaces/{workspace_id}/snapshots/{snapshot_id}/freeze-article"
)
def freeze_snapshot_to_article_api(
    workspace_id: int, snapshot_id: int
) -> Dict[str, Any]:
    """Freezes a workspace snapshot and publishes it as a knowledge base article (FetchedPage)."""
    import markdown as md_lib

    with db_session() as session:
        ws = session.query(Workspace).filter_by(id=workspace_id).first()
        if not ws:
            raise HTTPException(status_code=404, detail="Workspace not found")

        snapshot = (
            session.query(WorkspaceSnapshot)
            .filter_by(workspace_id=workspace_id, id=snapshot_id)
            .first()
        )
        if not snapshot:
            raise HTTPException(status_code=404, detail="Snapshot not found")

        files_map = json.loads(snapshot.files_snapshot or "{}")
        file_paths = sorted(files_map.keys())

        # Build clean Markdown document
        doc_lines = [
            f"# Workspace: {ws.name} ({snapshot.version_tag})",
            "",
            f"> **Description**: {snapshot.description or ws.description or 'Workspace snapshot code archive.'}",
            f"> **Created At**: {snapshot.created_at} | **Total Files**: {len(file_paths)}",
            "",
            "## File Manifest",
        ]
        for p in file_paths:
            doc_lines.append(f"- `{p}`")
        doc_lines.append("")
        doc_lines.append("## Source Code")

        for p in file_paths:
            finfo = files_map[p]
            lang = finfo.get("language") or _infer_language(p)
            code = finfo.get("content", "")
            doc_lines.append(f"### `{p}`")
            doc_lines.append(f"```{lang}\n{code}\n```")
            doc_lines.append("")

        full_md = "\n".join(doc_lines)
        html_content = md_lib.markdown(
            full_md, extensions=["fenced_code", "tables"]
        )

        article_url = f"workspace://{ws.id}/snapshot/{snapshot.version_tag}"
        article_title = f"{ws.name} ({snapshot.version_tag})"

        page = session.query(FetchedPage).filter_by(url=article_url).first()
        now_str = datetime.now().isoformat()
        if page:
            page.title = article_title
            page.description = snapshot.description or ws.description
            page.md_content = full_md
            page.html_content = html_content
            page.fetched_at = now_str
            page.exclude_from_general = 0
            page.tags = (
                f"workspace, {ws.name.lower()}, {snapshot.version_tag.lower()}"
            )
        else:
            page = FetchedPage(
                url=article_url,
                title=article_title,
                description=snapshot.description or ws.description,
                html_content=html_content,
                md_content=full_md,
                fetched_at=now_str,
                links="[]",
                keywords="[]",
                tags=f"workspace, {ws.name.lower()}, {snapshot.version_tag.lower()}",
                exclude_from_general=0,
            )
            session.add(page)

        session.commit()

        return {
            "status": "published",
            "article_url": article_url,
            "title": article_title,
            "message": "Snapshot frozen and published as a Knowledge Base article.",
        }


@router.post("/api/workspaces/{workspace_id}/agent/chat")
def workspace_agent_chat_api(
    workspace_id: int, payload: WorkspaceAgentChatRequest
) -> Dict[str, Any]:
    """Autonomous coding agent endpoint: combines tev1 decision gating with tool execution

    (create_file, read_file, edit_file) to safely inspect and modify workspace files.
    """
    user_prompt = payload.message.strip()
    if not user_prompt:
        raise HTTPException(status_code=400, detail="Prompt is required")

    model_name = payload.model or getattr(config, "ollama_model", "gemma4:latest")
    client = _get_ollama_client()

    with db_session() as session:
        ws = session.query(Workspace).filter_by(id=workspace_id).first()
        if not ws:
            raise HTTPException(status_code=404, detail="Workspace not found")

        try:
            res = execute_agent_step(
                session=session,
                client=client,
                workspace_id=workspace_id,
                user_prompt=user_prompt,
                coding_model=model_name,
                active_file=payload.active_file,
                tev1_model="tev1",
            )
            return {
                "status": "success",
                "reply": res.get("reply", ""),
                "decision": res.get("decision", {}),
                "read_actions": res.get("read_actions", []),
                "executed_tools": res.get("executed_tools", []),
                "model": model_name,
            }
        except Exception as e:
            return {
                "status": "error",
                "reply": f"Note: Ollama server connection or execution failed ({str(e)}). Please verify your Ollama server is running and the model '{model_name}' is installed.",
                "model": model_name,
            }

