"""
FastAPI Router for Notes & Code Ingestion, Monaco Browser Editor,
and Obsidian Vault Directory Mirroring in kb-web.
"""

from datetime import datetime
import io
import json
import os
from pathlib import Path
import re
from typing import Optional, Dict, Any, List
from urllib.parse import quote_plus, unquote_plus
import zipfile

from fastapi import APIRouter, Query, HTTPException, Request, BackgroundTasks, UploadFile, File, Form, Depends
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from ..base import db_session, config, _jinja_env, COOKIE_NAME, verify_session_token, verify_auth
from ..models_orm import Note, FetchedPage, ChunkEmbedding
from ..models import NoteCreateRequest, NoteUpdateRequest, HTMLPage
from ..utils import (
    _get_ollama_client,
    extract_tags_content,
    extract_valid_urls,
    generate_note_title,
    generate_gemma_embeddings_for_page,
)
from ..agent_memory import post_agent_memory

router = APIRouter(tags=["Notes"])


def _process_note_in_background(note_id: int):
    """Applies tagging, link extraction (filtered for actual URLs), titling, and embeddings for an ingested note.

    Explicitly skips AI wiki generation. Posts activity to Agent Memory and triggers taxonomy classification.
    """
    with db_session() as session:
        note = session.query(Note).filter_by(id=note_id).first()
        if not note:
            return

        client = _get_ollama_client()
        content = note.content or ""
        note_url = note.url

        # 1. Automatic titling if title is blank or generic
        current_title = (note.title or "").strip()
        if not current_title or current_title.lower() in ("untitled", "untitled note"):
            new_title = generate_note_title(content, config, client)
            note.title = new_title

        # 2. Tagging via Ollama
        try:
            if not note.tags or note.tags == "[]":
                tags = extract_tags_content(content, config, client)
                note.tags = json.dumps(tags)
        except Exception as e:
            print(f"Failed to generate tags for note {note_id}: {e}")

        # 3. Link extraction strictly filtered for valid HTTP/HTTPS URLs
        extracted_links: List[str] = []
        try:
            extracted_links = extract_valid_urls(content)
            note.links = json.dumps(extracted_links)
        except Exception as e:
            print(f"Failed to extract URLs for note {note_id}: {e}")

        # 4. Skip wiki generation: note.wiki_summary remains empty / ungenerated

        # 5. Mirror into FetchedPage so it is unified in main library & search
        page = session.query(FetchedPage).filter_by(url=note.url).first()
        if not page:
            page = FetchedPage(
                url=note.url,
                title=f"📝 {note.title}",
                html_content="",
                md_content=note.content,
                description=note.content[:500] if note.content else "",
                tags=note.tags or "[]",
                links=note.links or "[]",
                keywords="[]",
                fetched_at=datetime.now().isoformat(),
            )
            session.add(page)
        else:
            page.title = f"📝 {note.title}"
            page.md_content = note.content
            page.description = note.content[:500] if note.content else ""
            page.tags = note.tags or "[]"
            page.links = note.links or "[]"

        # 6. Post event to Agent Memory board
        try:
            post_agent_memory(
                session=session,
                agent_name="NotesIngestionAgent",
                channel="ingestion",
                topic="notes",
                content=(
                    f"Processed note '{note.title}' (ID: {note.id}): titling applied, "
                    f"{len(extracted_links)} web URLs extracted, tags {note.tags}. "
                    "Skipped wiki generation."
                ),
                memory_type="observation",
                metadata={"note_id": note.id, "title": note.title, "url_count": len(extracted_links)},
            )
        except Exception as e:
            print(f"Failed to post note ingestion memory: {e}")

        session.commit()

    # 7. Generate chunk embeddings
    try:
        generate_gemma_embeddings_for_page(None, note_url, config, client)
    except Exception as e:
        print(f"Failed to generate embeddings for note {note_id}: {e}")

    # 8. Trigger taxonomy classification
    try:
        from ..taxonomy_state_machine import classify_single_item
        classify_single_item("note", note_id)
    except Exception as e:
        print(f"Taxonomy auto-classification skipped/failed for note {note_id}: {e}")


# --- Helpers & API Endpoints ---

def build_nested_folder_tree(notes: list, item_transform=None) -> Dict[str, Any]:
    """Builds a recursive nested folder tree per vault for hierarchical directory navigation.

    Structure per vault:
    {
        "name": vault_name,
        "subfolders": {
            folder_segment: {
                "name": folder_segment,
                "path": cumulative_path,
                "subfolders": { ... },
                "notes": [ item, ... ],
                "total_count": int,
            }
        },
        "notes": [ item, ... ],
        "total_count": int,
    }
    """
    def _create_folder_node(name: str, path: str):
        return {
            "name": name,
            "path": path,
            "subfolders": {},
            "notes": [],
            "total_count": 0,
        }

    tree: Dict[str, Any] = {}
    for n in notes:
        v = n.vault_name or "Personal"
        if v not in tree:
            tree[v] = _create_folder_node(v, "")

        item = item_transform(n) if item_transform else n

        raw_path = (n.folder_path or "").strip("/\\").replace("\\", "/")
        if not raw_path or raw_path.lower() == "root":
            tree[v]["notes"].append(item)
            continue

        parts = [p.strip() for p in raw_path.split("/") if p.strip()]
        current_node = tree[v]
        curr_path_accum = []
        for part in parts:
            curr_path_accum.append(part)
            full_part_path = "/".join(curr_path_accum)
            if part not in current_node["subfolders"]:
                current_node["subfolders"][part] = _create_folder_node(part, full_part_path)
            current_node = current_node["subfolders"][part]

        current_node["notes"].append(item)

    # Calculate total_count recursively
    def _sum_counts(node: Dict[str, Any]) -> int:
        count = len(node["notes"])
        for sub in node["subfolders"].values():
            count += _sum_counts(sub)
        node["total_count"] = count
        return count

    for v_node in tree.values():
        _sum_counts(v_node)

    return tree


@router.get("/api/notes")
def list_notes_api(
    vault: Optional[str] = Query(default=None),
    q: Optional[str] = Query(default=None),
) -> Dict[str, Any]:
    """Returns all notes grouped by vault and directory folder hierarchy."""
    with db_session() as session:
        query = session.query(Note)
        if vault and isinstance(vault, str):
            query = query.filter_by(vault_name=vault)
        if q and isinstance(q, str):
            term = f"%{q.strip()}%"
            query = query.filter(Note.title.ilike(term) | Note.content.ilike(term))

        notes = query.order_by(Note.folder_path.asc(), Note.title.asc()).all()

        # Build recursive nested tree
        nested_tree = build_nested_folder_tree(notes, item_transform=lambda n: {
            "id": n.id,
            "title": n.title,
            "url": n.url,
            "safe_url": quote_plus(n.url),
            "syntax": n.syntax,
            "updated_at": n.updated_at,
        })

        # Flat hierarchy tree for backwards compatibility
        tree = {}
        for n in notes:
            v = n.vault_name or "Personal"
            if v not in tree:
                tree[v] = {}
            folder = n.folder_path or "Root"
            if folder not in tree[v]:
                tree[v][folder] = []
            tree[v][folder].append({
                "id": n.id,
                "title": n.title,
                "url": n.url,
                "safe_url": quote_plus(n.url),
                "syntax": n.syntax,
                "updated_at": n.updated_at,
            })

        return {
            "total": len(notes),
            "tree": tree,
            "nested_tree": nested_tree,
            "notes": [
                {
                    "id": n.id,
                    "title": n.title,
                    "url": n.url,
                    "safe_url": quote_plus(n.url),
                    "syntax": n.syntax,
                    "vault_name": n.vault_name,
                    "folder_path": n.folder_path,
                    "updated_at": n.updated_at,
                }
                for n in notes
            ],
        }



@router.post("/api/notes/paste")
def paste_note(payload: NoteCreateRequest, background_tasks: BackgroundTasks) -> Dict[str, Any]:
    """Pastes raw markdown or code as an uploaded note item and triggers AI wiki generation."""
    content = payload.content.strip()
    if not content:
        raise HTTPException(status_code=400, detail="Note content cannot be empty")

    title = payload.title
    if not title:
        # Extract first header or first line
        lines = content.splitlines()
        first_line = lines[0].strip() if lines else "Untitled Note"
        title = re.sub(r"^[#\s\-*]+", "", first_line)[:60] or "Untitled Note"

    vault = payload.vault_name or "Personal"
    folder = payload.folder_path.strip("/\\") if payload.folder_path else ""
    safe_slug = re.sub(r"[^\w\-_\.]", "_", title.lower())
    url = f"note://{vault}/{folder}/{safe_slug}" if folder else f"note://{vault}/{safe_slug}"

    now = datetime.now().isoformat()
    with db_session() as session:
        # Check existing note with same URL
        existing = session.query(Note).filter_by(url=url).first()
        if existing:
            url = f"{url}_{int(datetime.now().timestamp())}"

        note = Note(
            url=url,
            title=title,
            content=content,
            syntax=payload.syntax or "markdown",
            folder_path=folder,
            vault_name=vault,
            created_at=now,
            updated_at=now,
        )
        session.add(note)
        session.commit()
        session.refresh(note)
        note_id = note.id

    background_tasks.add_task(_process_note_in_background, note_id)

    return {
        "status": "created",
        "id": note_id,
        "title": title,
        "url": url,
        "safe_url": quote_plus(url),
    }


@router.post("/api/notes/upload-vault")
async def upload_obsidian_vault(
    vault_file: UploadFile = File(...),
    vault_name: str = Form("Obsidian Vault"),
    background_tasks: BackgroundTasks = None,
) -> Dict[str, Any]:
    """Uploads a ZIP archive of an Obsidian vault, extracting notes and mirroring structure."""
    if not vault_file.filename.endswith(".zip"):
        raise HTTPException(status_code=400, detail="Please upload a .zip archive of your Obsidian vault")

    zip_bytes = await vault_file.read()
    ingested_count = 0

    # Ensure media attachment directory exists
    media_vault_dir = config.configs_dir.parent / "media" / "notes" / re.sub(r"[^\w\-]", "_", vault_name)
    media_vault_dir.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        for filename in z.namelist():
            # Skip hidden files or __MACOSX
            if "/." in filename or filename.startswith(".") or "__MACOSX" in filename:
                continue

            # If it's a media asset (images, pdfs), unpack to media directory
            lower_name = filename.lower()
            if any(lower_name.endswith(ext) for ext in [".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".pdf"]):
                try:
                    dest_path = (media_vault_dir / filename).resolve()
                    # Prevent directory traversal / ZipSlip vulnerability
                    if not str(dest_path).startswith(str(media_vault_dir.resolve())):
                        continue
                    dest_path.parent.mkdir(parents=True, exist_ok=True)
                    with open(dest_path, "wb") as f:
                        f.write(z.read(filename))
                except Exception:
                    continue
                continue

            # If it's a markdown note
            if lower_name.endswith(".md"):
                path_parts = Path(filename).parts
                # Prevent directory traversal in note folder paths
                if ".." in path_parts:
                    continue
                try:
                    content = z.read(filename).decode("utf-8", errors="replace")
                except Exception:
                    continue

                folder_path = "/".join(path_parts[:-1]) if len(path_parts) > 1 else ""
                note_title = Path(filename).stem
                safe_slug = re.sub(r"[^\w\-_\.]", "_", note_title.lower())
                url = f"note://{vault_name}/{folder_path}/{safe_slug}" if folder_path else f"note://{vault_name}/{safe_slug}"

                now = datetime.now().isoformat()
                with db_session() as session:
                    existing = session.query(Note).filter_by(url=url).first()
                    if not existing:
                        note = Note(
                            url=url,
                            title=note_title,
                            content=content,
                            syntax="markdown",
                            folder_path=folder_path,
                            vault_name=vault_name,
                            created_at=now,
                            updated_at=now,
                        )
                        session.add(note)
                        session.commit()
                        session.refresh(note)
                        if background_tasks:
                            background_tasks.add_task(_process_note_in_background, note.id)
                        ingested_count += 1
                    else:
                        existing.content = content
                        existing.updated_at = now
                        session.commit()
                        if background_tasks:
                            background_tasks.add_task(_process_note_in_background, existing.id)
                        ingested_count += 1

    return {
        "status": "success",
        "vault_name": vault_name,
        "notes_ingested": ingested_count,
    }


@router.get("/api/notes/tree")
def get_notes_tree() -> Dict[str, Any]:
    """Returns directory tree structure of notes across vaults."""
    res = list_notes_api(vault=None, q=None)
    return {"vaults": list(res["tree"].keys()), "tree": res["tree"], "total": res["total"]}


@router.get("/api/notes/{note_id}")
def get_note_detail(note_id: int) -> Dict[str, Any]:
    """Retrieves full content and metadata of a note for Monaco Editor."""
    with db_session() as session:
        note = session.query(Note).filter_by(id=note_id).first()
        if not note:
            raise HTTPException(status_code=404, detail="Note not found")

        parsed_links = []
        try:
            parsed_links = json.loads(note.links or "[]")
        except Exception:
            pass
        parsed_tags = []
        try:
            parsed_tags = json.loads(note.tags or "[]")
        except Exception:
            pass

        return {
            "id": note.id,
            "title": note.title,
            "url": note.url,
            "content": note.content,
            "syntax": note.syntax,
            "folder_path": note.folder_path,
            "vault_name": note.vault_name,
            "wiki_summary": note.wiki_summary,
            "links": parsed_links,
            "tags": parsed_tags,
            "updated_at": note.updated_at,
        }


@router.put("/api/notes/{note_id}")
def update_note(note_id: int, payload: NoteUpdateRequest, background_tasks: BackgroundTasks) -> Dict[str, Any]:
    """Updates note content and re-indexes embeddings."""
    with db_session() as session:
        note = session.query(Note).filter_by(id=note_id).first()
        if not note:
            raise HTTPException(status_code=404, detail="Note not found")

        if payload.title:
            note.title = payload.title
        note.content = payload.content
        if payload.syntax:
            note.syntax = payload.syntax
        if payload.folder_path is not None:
            note.folder_path = payload.folder_path
        note.updated_at = datetime.now().isoformat()
        session.commit()

    background_tasks.add_task(_process_note_in_background, note_id)
    return {"status": "updated", "id": note_id}


# --- UI Pages ---

@router.get("/notes", response_class=HTMLResponse)
def view_notes_dashboard(request: Request):
    """HTML Dashboard displaying notes hierarchy, Obsidian vaults, and paste modal."""
    token = request.cookies.get(COOKIE_NAME)
    is_admin = bool(token and verify_session_token(token))

    with db_session() as session:
        notes = session.query(Note).order_by(Note.updated_at.desc()).all()
        nested_tree = build_nested_folder_tree(notes)

        template = _jinja_env.get_template("notes_list.j2.html")
        html_content = template.render(
            notes=notes,
            tree=nested_tree,
            total=len(notes),
            is_admin=is_admin,
        )
    return HTMLResponse(content=html_content)


@router.get("/notes/editor", response_class=HTMLResponse)
@router.get("/notes/edit", response_class=HTMLResponse)
def view_monaco_editor(
    request: Request,
    id: Optional[int] = Query(None),
    url: Optional[str] = Query(None),
):
    """Monaco Editor (VS Code Browser) page for editing notes with live Markdown preview."""
    token = request.cookies.get(COOKIE_NAME)
    is_admin = bool(token and verify_session_token(token))

    with db_session() as session:
        note = None
        if id:
            note = session.query(Note).filter_by(id=id).first()
        elif url:
            decoded_url = unquote_plus(url)
            note = session.query(Note).filter_by(url=decoded_url).first()

        template = _jinja_env.get_template("note_editor.j2.html")
        html_content = template.render(
            note=note,
            is_admin=is_admin,
        )
    return HTMLResponse(content=html_content)
