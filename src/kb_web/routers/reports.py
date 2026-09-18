"""
Dynamic ERP-Style Custom Report Builder and Data Grid Router.

Supports:
- Dynamic table introspection & cross-table joins (fetched_pages, youtube_videos, notes, chunk_embeddings, collections, chat_conversations)
- Multi-column selection with lazy placeholder projection for heavy columns (HTML, Markdown, Vectors, Raw Content)
- Column sorting, grouping, filtering, and pagination
- Saved report views & configuration persistence
- On-demand streaming exports to CSV, JSON, and Excel (.xlsx)
- Scheduled report export jobs
"""

import io
import csv
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import text

from ..base import _jinja_env, db_session, verify_auth
from ..models_orm import (
    ChatConversation,
    ChatMessage,
    ChunkEmbedding,
    Collection,
    CollectionItem,
    FetchedPage,
    Note,
    SavedReportView,
    ScheduledReportJob,
    SiteWiki,
    YouTubeVideo,
)

router = APIRouter(prefix="", tags=["reports"])

# Heavy columns that should NOT be loaded over the wire during standard data grid browsing
HEAVY_COLUMNS = {
    "fetched_pages.html_content",
    "fetched_pages.md_content",
    "notes.content",
    "notes.wiki_summary",
    "site_wikis.wiki_content",
    "chunk_embeddings.chunk_vector",
}

# Pre-defined schema metadata for reporting introspection
TABLE_METADATA = {
    "fetched_pages": {
        "label": "Articles & Web Pages",
        "pk": "url",
        "columns": [
            {"name": "url", "label": "Page URL", "type": "string", "is_heavy": False},
            {"name": "title", "label": "Title", "type": "string", "is_heavy": False},
            {"name": "description", "label": "AI Description", "type": "string", "is_heavy": False},
            {"name": "fetched_at", "label": "Ingested Date", "type": "datetime", "is_heavy": False},
            {"name": "tags", "label": "Curated Tags (JSON)", "type": "string", "is_heavy": False},
            {"name": "keywords", "label": "Keywords", "type": "string", "is_heavy": False},
            {"name": "collection_id", "label": "Collection ID", "type": "int", "is_heavy": False},
            {"name": "html_content", "label": "Raw HTML Payload", "type": "string", "is_heavy": True},
            {"name": "md_content", "label": "Synthesized Markdown", "type": "string", "is_heavy": True},
        ],
        "allowable_joins": ["youtube_videos", "chunk_embeddings", "chat_conversations", "collections"],
    },
    "youtube_videos": {
        "label": "YouTube & Media Videos",
        "pk": "url",
        "columns": [
            {"name": "url", "label": "Video URL", "type": "string", "is_heavy": False},
            {"name": "video_id", "label": "YouTube ID", "type": "string", "is_heavy": False},
            {"name": "creator", "label": "Channel / Creator", "type": "string", "is_heavy": False},
            {"name": "channel_id", "label": "Channel ID", "type": "string", "is_heavy": False},
            {"name": "duration", "label": "Duration (sec)", "type": "int", "is_heavy": False},
            {"name": "view_count", "label": "View Count", "type": "int", "is_heavy": False},
            {"name": "thumbnail_url", "label": "Thumbnail URL", "type": "string", "is_heavy": False},
            {"name": "local_path", "label": "Local Media Path", "type": "string", "is_heavy": False},
            {"name": "updated_at", "label": "Updated At", "type": "datetime", "is_heavy": False},
        ],
        "allowable_joins": ["fetched_pages"],
    },
    "notes": {
        "label": "Notes & Code Snippets",
        "pk": "id",
        "columns": [
            {"name": "id", "label": "Note ID", "type": "int", "is_heavy": False},
            {"name": "title", "label": "Title", "type": "string", "is_heavy": False},
            {"name": "url", "label": "Note URI / Slug", "type": "string", "is_heavy": False},
            {"name": "vault_name", "label": "Vault / Collection", "type": "string", "is_heavy": False},
            {"name": "folder_path", "label": "Folder Path", "type": "string", "is_heavy": False},
            {"name": "syntax", "label": "Syntax / Language", "type": "string", "is_heavy": False},
            {"name": "created_at", "label": "Created Date", "type": "datetime", "is_heavy": False},
            {"name": "content", "label": "Raw Note Content", "type": "string", "is_heavy": True},
            {"name": "wiki_summary", "label": "AI Wiki Summary", "type": "string", "is_heavy": True},
        ],
        "allowable_joins": ["chunk_embeddings", "chat_conversations"],
    },
    "chunk_embeddings": {
        "label": "Vector Embeddings Chunks",
        "pk": "id",
        "columns": [
            {"name": "id", "label": "Chunk ID", "type": "int", "is_heavy": False},
            {"name": "source_type", "label": "Source Type", "type": "string", "is_heavy": False},
            {"name": "source_id", "label": "Parent Document URL", "type": "string", "is_heavy": False},
            {"name": "source_title", "label": "Parent Title", "type": "string", "is_heavy": False},
            {"name": "chunk_number", "label": "Chunk Index", "type": "int", "is_heavy": False},
            {"name": "model_name", "label": "Embedding Model", "type": "string", "is_heavy": False},
            {"name": "chunk_content", "label": "Chunk Text Excerpt", "type": "string", "is_heavy": False},
            {"name": "chunk_vector", "label": "Vector Embedding", "type": "vector", "is_heavy": True},
        ],
        "allowable_joins": ["fetched_pages", "notes"],
    },
    "chat_conversations": {
        "label": "Ollama Chat Conversations",
        "pk": "id",
        "columns": [
            {"name": "id", "label": "Conversation ID", "type": "int", "is_heavy": False},
            {"name": "source_id", "label": "Document URL", "type": "string", "is_heavy": False},
            {"name": "source_type", "label": "Source Type", "type": "string", "is_heavy": False},
            {"name": "title", "label": "Thread Title", "type": "string", "is_heavy": False},
            {"name": "created_at", "label": "Started At", "type": "datetime", "is_heavy": False},
            {"name": "updated_at", "label": "Last Active", "type": "datetime", "is_heavy": False},
        ],
        "allowable_joins": ["fetched_pages", "notes"],
    },
    "collections": {
        "label": "Virtual Collections",
        "pk": "id",
        "columns": [
            {"name": "id", "label": "Collection ID", "type": "int", "is_heavy": False},
            {"name": "title", "label": "Title", "type": "string", "is_heavy": False},
            {"name": "visibility", "label": "Visibility", "type": "string", "is_heavy": False},
            {"name": "created_at", "label": "Created Date", "type": "datetime", "is_heavy": False},
        ],
        "allowable_joins": ["fetched_pages"],
    },
    "site_wikis": {
        "label": "Domain Site Wikis",
        "pk": "site",
        "columns": [
            {"name": "site", "label": "Domain / Host", "type": "string", "is_heavy": False},
            {"name": "updated_at", "label": "Updated At", "type": "datetime", "is_heavy": False},
            {"name": "wiki_content", "label": "Wiki Markdown", "type": "string", "is_heavy": True},
        ],
        "allowable_joins": [],
    },
}


class FilterCondition(BaseModel):
    column: str
    operator: str = Field("eq", description="eq, neq, contains, not_contains, gt, gte, lt, lte, is_null, is_not_null, in")
    value: Any = None


class ReportQueryRequest(BaseModel):
    base_table: str = "fetched_pages"
    columns: List[str] = Field(default_factory=lambda: ["fetched_pages.url", "fetched_pages.title", "fetched_pages.fetched_at"])
    joins: List[str] = Field(default_factory=list)
    filters: List[FilterCondition] = Field(default_factory=list)
    sort_by: Optional[str] = "fetched_pages.fetched_at"
    sort_order: str = "desc"
    group_by: Optional[str] = None
    limit: int = 50
    offset: int = 0
    fetch_heavy: bool = False


class SavedReportCreateRequest(BaseModel):
    name: str
    description: Optional[str] = ""
    base_table: str
    config_json: Dict[str, Any]


class ScheduledReportCreateRequest(BaseModel):
    name: str
    view_id: Optional[int] = None
    export_format: str = "xlsx"  # xlsx, csv, json
    schedule_cron: str = "0 0 * * *"
    destination_path: Optional[str] = None


def _format_heavy_placeholder(col_name: str, val: Any) -> str:
    """Format heavy columns (HTML, Markdown, Vectors, Raw Content) as lightweight descriptive placeholders."""
    if val is None:
        return "[Empty]"
    if "html_content" in col_name:
        s = str(val)
        return f"[HTML: {len(s):,} chars]" if s else "[Empty HTML]"
    if "md_content" in col_name or "wiki_content" in col_name or "wiki_summary" in col_name:
        s = str(val)
        return f"[Markdown: {len(s):,} chars]" if s else "[Empty Markdown]"
    if "content" in col_name:
        s = str(val)
        return f"[Content: {len(s):,} chars]" if s else "[Empty Content]"
    if "chunk_vector" in col_name or "vector" in col_name:
        try:
            if isinstance(val, str):
                vec = json.loads(val)
                return f"[Vector: {len(vec)}-dim]"
            elif hasattr(val, "__len__"):
                return f"[Vector: {len(val)}-dim]"
        except Exception:
            pass
        return "[Vector: 768-dim]"
    return str(val)


def _build_sql_query(
    req: ReportQueryRequest,
    fetch_heavy: bool = False,
    is_count: bool = False,
) -> tuple[str, dict]:
    """Constructs sanitized SQL select or count queries across selected tables and joins."""
    base_table = req.base_table if req.base_table in TABLE_METADATA else "fetched_pages"
    
    # Columns to select
    selected_cols = []
    if is_count:
        select_clause = f"COUNT(*) as total_count"
    else:
        for c in req.columns:
            parts = c.split(".")
            if len(parts) == 2 and parts[0] in TABLE_METADATA:
                t_name, col_name = parts
                valid_col_names = [col["name"] for col in TABLE_METADATA[t_name]["columns"]]
                if col_name in valid_col_names:
                    selected_cols.append(f"{t_name}.{col_name} AS \"{t_name}.{col_name}\"")
        if not selected_cols:
            selected_cols = [f"{base_table}.{TABLE_METADATA[base_table]['pk']} AS \"{base_table}.{TABLE_METADATA[base_table]['pk']}\""]
        select_clause = ", ".join(selected_cols)

    # From & Joins
    from_clause = base_table
    join_clauses = []
    joined_tables = set(req.joins)
    
    # Auto-include joins required by chosen columns or filters
    for col in req.columns:
        if "." in col:
            tbl = col.split(".")[0]
            if tbl != base_table and tbl in TABLE_METADATA:
                joined_tables.add(tbl)
    for f in req.filters:
        if "." in f.column:
            tbl = f.column.split(".")[0]
            if tbl != base_table and tbl in TABLE_METADATA:
                joined_tables.add(tbl)

    for jt in joined_tables:
        if jt == base_table:
            continue
        if base_table == "fetched_pages":
            if jt == "youtube_videos":
                join_clauses.append("LEFT JOIN youtube_videos ON youtube_videos.url = fetched_pages.url")
            elif jt == "chunk_embeddings":
                join_clauses.append("LEFT JOIN chunk_embeddings ON chunk_embeddings.source_id = fetched_pages.url")
            elif jt == "chat_conversations":
                join_clauses.append("LEFT JOIN chat_conversations ON chat_conversations.source_id = fetched_pages.url")
            elif jt == "collections":
                join_clauses.append("LEFT JOIN collections ON collections.id = fetched_pages.collection_id")
        elif base_table == "youtube_videos":
            if jt == "fetched_pages":
                join_clauses.append("LEFT JOIN fetched_pages ON fetched_pages.url = youtube_videos.url")
        elif base_table == "notes":
            if jt == "chunk_embeddings":
                join_clauses.append("LEFT JOIN chunk_embeddings ON chunk_embeddings.source_id = notes.url")
            elif jt == "chat_conversations":
                join_clauses.append("LEFT JOIN chat_conversations ON chat_conversations.source_id = notes.url")
        elif base_table == "chunk_embeddings":
            if jt == "fetched_pages":
                join_clauses.append("LEFT JOIN fetched_pages ON fetched_pages.url = chunk_embeddings.source_id")
            elif jt == "notes":
                join_clauses.append("LEFT JOIN notes ON notes.url = chunk_embeddings.source_id")
        elif base_table == "chat_conversations":
            if jt == "fetched_pages":
                join_clauses.append("LEFT JOIN fetched_pages ON fetched_pages.url = chat_conversations.source_id")
            elif jt == "notes":
                join_clauses.append("LEFT JOIN notes ON notes.url = chat_conversations.source_id")

    joins_sql = " ".join(join_clauses)

    # Where filters
    where_clauses = []
    params = {}
    for idx, f in enumerate(req.filters):
        if not f.column or "." not in f.column:
            continue
        tbl, col = f.column.split(".", 1)
        if tbl not in TABLE_METADATA:
            continue
        valid_cols = [x["name"] for x in TABLE_METADATA[tbl]["columns"]]
        if col not in valid_cols:
            continue
        
        col_expr = f"{tbl}.{col}"
        p_name = f"param_{idx}"
        
        op = f.operator.lower()
        if op == "eq":
            where_clauses.append(f"{col_expr} = :{p_name}")
            params[p_name] = f.value
        elif op == "neq":
            where_clauses.append(f"{col_expr} != :{p_name}")
            params[p_name] = f.value
        elif op == "contains":
            where_clauses.append(f"{col_expr} LIKE :{p_name}")
            params[p_name] = f"%{f.value}%"
        elif op == "not_contains":
            where_clauses.append(f"({col_expr} NOT LIKE :{p_name} OR {col_expr} IS NULL)")
            params[p_name] = f"%{f.value}%"
        elif op == "gt":
            where_clauses.append(f"{col_expr} > :{p_name}")
            params[p_name] = f.value
        elif op == "gte":
            where_clauses.append(f"{col_expr} >= :{p_name}")
            params[p_name] = f.value
        elif op == "lt":
            where_clauses.append(f"{col_expr} < :{p_name}")
            params[p_name] = f.value
        elif op == "lte":
            where_clauses.append(f"{col_expr} <= :{p_name}")
            params[p_name] = f.value
        elif op == "is_null":
            where_clauses.append(f"{col_expr} IS NULL")
        elif op == "is_not_null":
            where_clauses.append(f"{col_expr} IS NOT NULL")
        elif op == "in" and isinstance(f.value, list):
            in_params = []
            for sub_i, val in enumerate(f.value):
                sub_p = f"{p_name}_{sub_i}"
                in_params.append(f":{sub_p}")
                params[sub_p] = val
            if in_params:
                where_clauses.append(f"{col_expr} IN ({', '.join(in_params)})")

    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

    if is_count:
        sql = f"SELECT {select_clause} FROM {from_clause} {joins_sql} {where_sql}"
        return sql, params

    # Group By
    group_sql = ""
    if req.group_by and "." in req.group_by:
        gtbl, gcol = req.group_by.split(".", 1)
        if gtbl in TABLE_METADATA and gcol in [x["name"] for x in TABLE_METADATA[gtbl]["columns"]]:
            group_sql = f"GROUP BY {gtbl}.{gcol}"

    # Order By
    order_sql = ""
    if req.sort_by and "." in req.sort_by:
        stbl, scol = req.sort_by.split(".", 1)
        if stbl in TABLE_METADATA and scol in [x["name"] for x in TABLE_METADATA[stbl]["columns"]]:
            direction = "DESC" if req.sort_order.lower() == "desc" else "ASC"
            order_sql = f"ORDER BY {stbl}.{scol} {direction}"

    # Limit / Offset
    limit_val = min(max(1, req.limit), 500)
    offset_val = max(0, req.offset)
    pagination_sql = f"LIMIT {limit_val} OFFSET {offset_val}"

    sql = f"SELECT {select_clause} FROM {from_clause} {joins_sql} {where_sql} {group_sql} {order_sql} {pagination_sql}"
    return sql, params


# -----------------------------------------------------------------------------
# REST & Data Grid Endpoints
# -----------------------------------------------------------------------------

@router.get("/api/reports/tables")
def get_report_tables_metadata():
    """Returns introspection metadata for all queryable tables, column types, and heavy flags."""
    return {"tables": TABLE_METADATA}


@router.post("/api/reports/query")
def execute_report_query(req: ReportQueryRequest):
    """Executes dynamic report query with sorting, filtering, joins, and lazy placeholder representation."""
    with db_session() as session:
        # Total count
        count_sql, count_params = _build_sql_query(req, is_count=True)
        try:
            total_count = session.execute(text(count_sql), count_params).scalar() or 0
        except Exception:
            total_count = 0

        # Fetch records
        query_sql, query_params = _build_sql_query(req, fetch_heavy=req.fetch_heavy, is_count=False)
        result = session.execute(text(query_sql), query_params)
        keys = list(result.keys())
        raw_rows = [dict(row._mapping) for row in result.fetchall()]

        # Process heavy column placeholders if fetch_heavy is False
        processed_rows = []
        for r in raw_rows:
            row_dict = {}
            for k, v in r.items():
                if not req.fetch_heavy and k in HEAVY_COLUMNS:
                    row_dict[k] = _format_heavy_placeholder(k, v)
                else:
                    row_dict[k] = v
            processed_rows.append(row_dict)

        return {
            "columns": keys,
            "rows": processed_rows,
            "total_count": total_count,
            "page": (req.offset // req.limit) + 1 if req.limit else 1,
            "page_size": req.limit,
            "query_summary": {
                "base_table": req.base_table,
                "joins": req.joins,
                "filters_count": len(req.filters),
            }
        }


@router.get("/api/reports/views")
def list_saved_report_views():
    """List all saved custom report view templates."""
    with db_session() as session:
        views = session.query(SavedReportView).order_by(SavedReportView.created_at.desc()).all()
        return [
            {
                "id": v.id,
                "name": v.name,
                "description": v.description,
                "base_table": v.base_table,
                "config": {
                    "base_table": v.base_table,
                    "columns": json.loads(v.selected_columns) if v.selected_columns else [],
                    "joins": json.loads(v.joins_config) if v.joins_config else [],
                    "sort": json.loads(v.sort_config) if v.sort_config else {},
                    "filters": json.loads(v.filter_config) if v.filter_config else [],
                    "group": json.loads(v.group_config) if v.group_config else [],
                },
                "created_at": v.created_at,
                "updated_at": v.updated_at,
            }
            for v in views
        ]


@router.post("/api/reports/views")
def save_report_view(payload: SavedReportCreateRequest):
    """Save a report view definition for reuse."""
    with db_session() as session:
        c = payload.config_json
        view = SavedReportView(
            name=payload.name,
            description=payload.description or "",
            base_table=payload.base_table,
            selected_columns=json.dumps(c.get("columns", [])),
            joins_config=json.dumps(c.get("joins", [])),
            sort_config=json.dumps({"by": c.get("sort_by"), "order": c.get("sort_order")}),
            filter_config=json.dumps(c.get("filters", [])),
            group_config=json.dumps([c.get("group_by")] if c.get("group_by") else []),
            created_at=datetime.now().isoformat(),
            updated_at=datetime.now().isoformat(),
        )
        session.add(view)
        session.flush()
        view_id = view.id
        view_name = view.name
        return {"status": "success", "id": view_id, "name": view_name}


@router.delete("/api/reports/views/{view_id}")
def delete_report_view(view_id: int):
    """Delete a saved report view."""
    with db_session() as session:
        view = session.query(SavedReportView).filter_by(id=view_id).first()
        if not view:
            raise HTTPException(status_code=404, detail="Saved view not found.")
        session.delete(view)
        session.commit()
        return {"status": "success", "message": f"View {view_id} deleted."}


@router.post("/api/reports/export")
def export_report_data(req: ReportQueryRequest, format: str = Query("csv", pattern="^(csv|json|xlsx)$")):
    """Streams export data in CSV, JSON, or Excel (.xlsx) format."""
    req.limit = 5000
    req.offset = 0

    with db_session() as session:
        query_sql, query_params = _build_sql_query(req, fetch_heavy=req.fetch_heavy, is_count=False)
        result = session.execute(text(query_sql), query_params)
        keys = list(result.keys())
        raw_rows = [dict(row._mapping) for row in result.fetchall()]

        processed_rows = []
        for r in raw_rows:
            row_dict = {}
            for k, v in r.items():
                if not req.fetch_heavy and k in HEAVY_COLUMNS:
                    row_dict[k] = _format_heavy_placeholder(k, v)
                else:
                    row_dict[k] = v
            processed_rows.append(row_dict)

    timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    base_name = f"kb_report_{req.base_table}_{timestamp_str}"

    if format == "json":
        json_data = json.dumps(processed_rows, indent=2, default=str)
        return StreamingResponse(
            io.StringIO(json_data),
            media_type="application/json",
            headers={"Content-Disposition": f"attachment; filename={base_name}.json"},
        )

    elif format == "xlsx":
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = req.base_table[:30].capitalize()

        header_fill = PatternFill(start_color="4F46E5", end_color="4F46E5", fill_type="solid")
        header_font = Font(color="FFFFFF", bold=True)
        header_align = Alignment(horizontal="center", vertical="center")

        ws.append(keys)
        for col_num, _ in enumerate(keys, 1):
            cell = ws.cell(row=1, column=col_num)
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = header_align

        for r in processed_rows:
            ws.append([r.get(k) for k in keys])

        for col in ws.columns:
            max_len = max(len(str(cell.value or "")) for cell in col)
            col_letter = openpyxl.utils.get_column_letter(col[0].column)
            ws.column_dimensions[col_letter].width = min(max(max_len + 3, 10), 50)

        output_stream = io.BytesIO()
        wb.save(output_stream)
        output_stream.seek(0)

        return StreamingResponse(
            output_stream,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename={base_name}.xlsx"},
        )

    else:  # CSV default
        csv_stream = io.StringIO()
        writer = csv.DictWriter(csv_stream, fieldnames=keys)
        writer.writeheader()
        writer.writerows(processed_rows)
        csv_stream.seek(0)

        return StreamingResponse(
            csv_stream,
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename={base_name}.csv"},
        )


# -----------------------------------------------------------------------------
# Scheduled Report Jobs
# -----------------------------------------------------------------------------

@router.get("/api/reports/schedules")
def list_scheduled_jobs():
    """List all configured recurring export jobs."""
    with db_session() as session:
        jobs = session.query(ScheduledReportJob).order_by(ScheduledReportJob.id.desc()).all()
        return [
            {
                "id": j.id,
                "report_id": j.report_id,
                "export_format": j.export_format,
                "cron_expression": j.cron_expression,
                "destination": j.destination,
                "last_run_at": j.last_run_at,
                "next_run_at": j.next_run_at,
                "enabled": j.enabled,
                "created_at": j.created_at,
            }
            for j in jobs
        ]


@router.post("/api/reports/schedule")
def create_scheduled_job(payload: ScheduledReportCreateRequest):
    """Register a scheduled report job for recurring exports."""
    with db_session() as session:
        dest = payload.destination_path or os.path.expanduser("~/.kb/reports_export")
        os.makedirs(dest, exist_ok=True)

        job = ScheduledReportJob(
            report_id=payload.view_id,
            export_format=payload.export_format,
            cron_expression=payload.schedule_cron,
            destination=dest,
            last_run_at=None,
            next_run_at=datetime.now().isoformat(),
            enabled=1,
            created_at=datetime.now().isoformat(),
        )
        session.add(job)
        session.flush()
        job_id = job.id
        return {"status": "success", "id": job_id}


@router.delete("/api/reports/schedule/{job_id}")
def delete_scheduled_job(job_id: int):
    """Delete a scheduled export job."""
    with db_session() as session:
        job = session.query(ScheduledReportJob).filter_by(id=job_id).first()
        if not job:
            raise HTTPException(status_code=404, detail="Job not found.")
        session.delete(job)
        session.commit()
        return {"status": "success", "message": f"Job {job_id} deleted."}


@router.post("/api/reports/schedule/{job_id}/run")
def run_scheduled_job_now(job_id: int):
    """Executes a scheduled job immediately and writes file to destination folder."""
    with db_session() as session:
        job = session.query(ScheduledReportJob).filter_by(id=job_id).first()
        if not job:
            raise HTTPException(status_code=404, detail="Job not found.")
        
        # Load view config if linked
        config = {}
        if job.report_id:
            view = session.query(SavedReportView).filter_by(id=job.report_id).first()
            if view:
                config = {
                    "base_table": view.base_table,
                    "columns": json.loads(view.selected_columns) if view.selected_columns else [],
                    "joins": json.loads(view.joins_config) if view.joins_config else [],
                    "filters": json.loads(view.filter_config) if view.filter_config else [],
                }
        
        req = ReportQueryRequest(**config) if config else ReportQueryRequest()
        req.limit = 5000
        req.offset = 0

        query_sql, query_params = _build_sql_query(req, fetch_heavy=False, is_count=False)
        result = session.execute(text(query_sql), query_params)
        keys = list(result.keys())
        raw_rows = [dict(row._mapping) for row in result.fetchall()]

        dest_dir = Path(job.destination or os.path.expanduser("~/.kb/reports_export"))
        dest_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"report_job_{job.id}_{timestamp}.{job.export_format}"
        file_path = dest_dir / filename

        if job.export_format == "csv":
            with open(file_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=keys)
                writer.writeheader()
                for r in raw_rows:
                    writer.writerow({k: _format_heavy_placeholder(k, v) if k in HEAVY_COLUMNS else v for k, v in r.items()})
        elif job.export_format == "json":
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(raw_rows, f, indent=2, default=str)
        elif job.export_format == "xlsx":
            import openpyxl
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = "Report"
            ws.append(keys)
            for r in raw_rows:
                ws.append([_format_heavy_placeholder(k, v) if k in HEAVY_COLUMNS else v for k, v in r.items()])
            wb.save(str(file_path))

        job.last_run_at = datetime.now().isoformat()
        session.commit()

        return {
            "status": "success",
            "message": f"Export generated at {file_path}",
            "filename": filename,
            "file_size": file_path.stat().st_size,
        }


# -----------------------------------------------------------------------------
# Frontend Reports UI
# -----------------------------------------------------------------------------

@router.get("/reports", response_class=HTMLResponse)
def view_reports_dashboard(request: Request, user=Depends(verify_auth)):
    """Renders the ERP Custom Report & Data Grid interactive builder."""
    with db_session() as session:
        saved_views = session.query(SavedReportView).order_by(SavedReportView.name.asc()).all()
        schedules = session.query(ScheduledReportJob).order_by(ScheduledReportJob.id.desc()).all()
        template = _jinja_env.get_template("reports.j2.html")
        html_content = template.render(
            request=request,
            saved_views=saved_views,
            schedules=schedules,
            tables_meta=TABLE_METADATA,
            heavy_columns=list(HEAVY_COLUMNS),
        )
    return HTMLResponse(content=html_content)
