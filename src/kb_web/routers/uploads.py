"""WebSocket and HTTP Document Ingestion Router supporting Docling conversions.

Provides:
- WebSocket endpoint `/api/import/file/upload` for client-side sliced chunk uploads.
- HTTP POST endpoint `/api/import/file` for direct single-request file uploads.
- Validates file extensions against non-blacklisted docling supported formats.
- Deduplicates file content via SHA-256 hashes.
- Converts documents via DoclingClient, saves markdown and docling JSON artifacts,
  and enqueues items into the background sources queue for tag/embedding extraction.
"""

import base64
import hashlib
import json
import logging
import mimetypes
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, UploadFile, File, Form, HTTPException, Depends
from sqlalchemy.orm import Session

from ..base import db_session, config, verify_session_token, COOKIE_NAME
from ..models_orm import UploadedDocument, FetchedPage, Source
from ..queue_processor import enqueue_source
from ..utils import (
    DoclingClient,
    DOCLING_SUPPORTED_EXTENSIONS,
)

logger = logging.getLogger("kb_web.uploads")

router = APIRouter(tags=["Document Ingestion"])


def _validate_extension(filename: str) -> str:
    """Validates that the file has an allowed, non-blacklisted extension."""
    if "." not in filename:
        raise ValueError(f"File '{filename}' lacks a file extension")
    ext = filename.rsplit(".", 1)[-1].lower()
    if ext not in DOCLING_SUPPORTED_EXTENSIONS:
        raise ValueError(f"Unsupported or blacklisted file format: .{ext}")
    return ext


def _process_uploaded_file(
    temp_file: Path,
    filename: str,
    file_size: int,
    collection_id: Optional[int] = None,
    custom_instructions: Optional[str] = None,
) -> Dict[str, Any]:
    """Computes SHA-256, converts document via DoclingClient, persists database records, and enqueues to sources."""
    # 1. Compute SHA-256 checksum
    hasher = hashlib.sha256()
    with open(temp_file, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    file_hash = hasher.hexdigest()

    ext = _validate_extension(filename)
    mime_type, _ = mimetypes.guess_type(filename)

    # 2. Prepare permanent storage directories
    uploads_dir = config.uploads_dir
    originals_dir = uploads_dir / "originals"
    originals_dir.mkdir(parents=True, exist_ok=True)
    docling_dir = uploads_dir / "docling_json"
    docling_dir.mkdir(parents=True, exist_ok=True)

    permanent_original = originals_dir / f"{file_hash}.{ext}"
    if not permanent_original.exists():
        temp_file.replace(permanent_original)
    else:
        temp_file.unlink(missing_ok=True)

    json_artifact_path = docling_dir / f"{file_hash}.json"

    # 3. Check for existing deduplicated document
    with db_session() as session:
        existing_doc = session.query(UploadedDocument).filter_by(file_hash=file_hash).first()
        if existing_doc and existing_doc.status == "parsed":
            logger.info(f"File {filename} ({file_hash}) already ingested. Reusing existing source.")
            return {
                "status": "completed",
                "message": "File already ingested (deduplicated)",
                "file_hash": file_hash,
                "source_id": existing_doc.source_id,
                "url": f"file://{permanent_original}",
                "page_url": f"file://{permanent_original}",
                "title": filename,
            }

    # 4. Convert document via Docling
    docling_client = DoclingClient()
    try:
        conv_result = docling_client.convert_file(permanent_original)
        if isinstance(conv_result, tuple):
            md_text = conv_result[0]
            docling_json = conv_result[1] if len(conv_result) > 1 else {}
        elif isinstance(conv_result, dict):
            md_text = conv_result.get("markdown", "")
            docling_json = conv_result.get("docling_json", {})
        else:
            md_text = str(conv_result)
            docling_json = {}
        if docling_json:
            with open(json_artifact_path, "w", encoding="utf-8") as jf:
                json.dump(docling_json, jf)
        status = "parsed"
        error_msg = None
    except Exception as conv_err:
        logger.error(f"Failed converting document {filename} ({file_hash}): {conv_err}")
        status = "failed"
        error_msg = str(conv_err)
        md_text = ""

    file_url = f"file://{permanent_original}"
    now_iso = datetime.now().isoformat()

    # 5. Populate FetchedPage and enqueue into background sources queue
    source_id = None
    if status == "parsed":
        with db_session() as session:
            existing_page = session.query(FetchedPage).filter_by(url=file_url).first()
            if existing_page:
                existing_page.title = filename
                existing_page.md_content = md_text
                existing_page.fetched_at = now_iso
                if collection_id is not None:
                    existing_page.collection_id = collection_id
            else:
                new_page = FetchedPage(
                    url=file_url,
                    title=filename,
                    md_content=md_text,
                    fetched_at=now_iso,
                    collection_id=collection_id,
                )
                session.add(new_page)

        # Enqueue with processor 3 (tagger -> embeddings) since markdown is already parsed
        source_id = enqueue_source(
            url_or_path=file_url,
            source_type="docling",
            collection_id=collection_id,
            custom_instructions=custom_instructions,
            initial_processor_id=3,  # start directly with tagger
        )

        with db_session() as session:
            page = session.query(FetchedPage).filter_by(url=file_url).first()
            if page:
                page.source_id = source_id

    # 6. Record in uploaded_documents table
    with db_session() as session:
        doc_record = session.query(UploadedDocument).filter_by(file_hash=file_hash).first()
        if doc_record:
            doc_record.status = status
            doc_record.error_message = error_msg
            doc_record.source_id = source_id
        else:
            doc_record = UploadedDocument(
                file_hash=file_hash,
                filename=filename,
                file_size=file_size,
                mime_type=mime_type,
                file_path=str(permanent_original),
                docling_json_path=str(json_artifact_path) if json_artifact_path.exists() else None,
                status=status,
                error_message=error_msg,
                uploaded_at=now_iso,
                source_id=source_id,
            )
            session.add(doc_record)

    if status == "failed":
        raise RuntimeError(error_msg or "Document conversion failed")

    return {
        "status": "completed",
        "file_hash": file_hash,
        "source_id": source_id,
        "url": file_url,
        "page_url": file_url,
        "title": filename,
    }


@router.websocket("/api/import/file/upload")
async def websocket_file_upload(websocket: WebSocket) -> None:
    """Accepts sliced chunk streaming of document files via WebSockets."""
    await websocket.accept()

    temp_path: Optional[Path] = None
    try:
        # Step 1: Handshake with file metadata
        init_data = await websocket.receive_json()
        filename = init_data.get("filename", "")
        file_size = int(init_data.get("file_size", 0))
        collection_id = init_data.get("collection_id")
        custom_instructions = init_data.get("custom_instructions")

        try:
            _validate_extension(filename)
        except ValueError as val_err:
            await websocket.send_json({"status": "error", "message": str(val_err)})
            await websocket.close(code=1003)
            return

        temp_dir = config.uploads_dir / "temp"
        temp_dir.mkdir(parents=True, exist_ok=True)
        temp_path = temp_dir / f"{uuid.uuid4().hex}_{filename}"

        await websocket.send_json({"status": "ready", "message": "Ready to receive chunk stream"})

        # Step 2: Stream chunks
        received_bytes = 0
        with open(temp_path, "wb") as f:
            while True:
                msg = await websocket.receive()
                if "text" in msg:
                    text_data = msg["text"]
                    if text_data in ("EOF", "done"):
                        break
                    try:
                        parsed = json.loads(text_data)
                        if parsed.get("action") in ("EOF", "done") or parsed.get("type") in ("EOF", "done"):
                            break
                        if "chunk" in parsed:
                            chunk_bytes = base64.b64decode(parsed["chunk"])
                            f.write(chunk_bytes)
                            received_bytes += len(chunk_bytes)
                    except Exception:
                        pass
                elif "bytes" in msg and msg["bytes"]:
                    chunk_bytes = msg["bytes"]
                    f.write(chunk_bytes)
                    received_bytes += len(chunk_bytes)

                pct = int((received_bytes / file_size) * 100) if file_size > 0 else 50
                await websocket.send_json({
                    "status": "uploading",
                    "progress": min(pct, 99),
                    "received": received_bytes,
                    "total": file_size,
                })

        # Step 3: Process and Convert Document
        await websocket.send_json({"status": "processing", "message": "Parsing document with Docling..."})

        result = _process_uploaded_file(
            temp_file=temp_path,
            filename=filename,
            file_size=received_bytes,
            collection_id=collection_id,
            custom_instructions=custom_instructions,
        )

        await websocket.send_json(result)

    except WebSocketDisconnect:
        logger.info("Client disconnected from file upload websocket.")
        if temp_path and temp_path.exists():
            temp_path.unlink(missing_ok=True)
    except Exception as e:
        logger.error(f"WebSocket upload error: {e}", exc_info=True)
        if temp_path and temp_path.exists():
            temp_path.unlink(missing_ok=True)
        try:
            await websocket.send_json({"status": "error", "message": str(e)})
        except Exception:
            pass


@router.post("/api/import/file")
async def http_file_upload(
    file: UploadFile = File(...),
    collection_id: Optional[int] = Form(None),
    custom_instructions: Optional[str] = Form(None),
) -> Dict[str, Any]:
    """HTTP fallback endpoint for standard multipart document uploads."""
    filename = file.filename or "uploaded_document"
    try:
        _validate_extension(filename)
    except ValueError as val_err:
        raise HTTPException(status_code=400, detail=str(val_err))

    temp_dir = config.uploads_dir / "temp"
    temp_dir.mkdir(parents=True, exist_ok=True)
    temp_path = temp_dir / f"{uuid.uuid4().hex}_{filename}"

    file_size = 0
    with open(temp_path, "wb") as f:
        while chunk := await file.read(65536):
            f.write(chunk)
            file_size += len(chunk)

    try:
        result = _process_uploaded_file(
            temp_file=temp_path,
            filename=filename,
            file_size=file_size,
            collection_id=collection_id,
            custom_instructions=custom_instructions,
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
