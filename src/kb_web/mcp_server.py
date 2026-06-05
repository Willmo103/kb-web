"""
Model Context Protocol (MCP) Server for the Knowledge Base Web Importer.
Exposes tools for agents to search and query local wiki articles.
"""

import json
import sqlite_utils
from mcp.server.fastmcp import FastMCP
from .config import Config
from .db import get_db

# Load configurations
config = Config()
mcp = FastMCP("KB Web")


def _get_db() -> sqlite_utils.Database:
    """Helper to retrieve a clean database handle."""
    return get_db(config)


@mcp.tool()
def list_articles() -> str:
    """Lists all saved articles in the Knowledge Base with their URL, title, tags, and fetch timestamp.

    Returns:
        str: JSON formatted string containing list of articles.
    """
    db = _get_db()
    if "fetched_pages" not in db.table_names():
        return "No articles found in Knowledge Base."

    rows = list(db["fetched_pages"].rows)
    if not rows:
        return "No articles found in Knowledge Base."

    result = []
    for r in rows:
        try:
            tags = json.loads(r.get("tags") or "[]")
        except Exception:
            tags = []
        result.append(
            {
                "title": r.get("title") or r.get("url"),
                "url": r.get("url"),
                "tags": tags,
                "fetched_at": r.get("fetched_at"),
            }
        )
    return json.dumps(result, indent=2)


@mcp.tool()
def get_article(url: str) -> str:
    """Retrieves the full details of a specific article by its URL, including its wiki description and tags.

    Args:
        url (str): The primary URL of the article to retrieve.

    Returns:
        str: JSON formatted string containing detailed article metadata.
    """
    db = _get_db()
    try:
        row = db["fetched_pages"].get(url)
        try:
            tags = json.loads(row.get("tags") or "[]")
        except Exception:
            tags = []
        return json.dumps(
            {
                "url": row.get("url"),
                "title": row.get("title"),
                "description": row.get("description"),  # wiki summary
                "tags": tags,
                "fetched_at": row.get("fetched_at"),
                "md_content_preview": (row.get("md_content") or "")[:2000],
            },
            indent=2,
        )
    except sqlite_utils.db.NotFoundError:
        return f"Article with URL '{url}' not found in Knowledge Base."


@mcp.tool()
def search_articles(query: str) -> str:
    """Searches for articles in the Knowledge Base matching the query string in their title, description, or tags.

    Args:
        query (str): The search phrase or keyword to match.

    Returns:
        str: JSON formatted list of matching articles.
    """
    db = _get_db()
    if "fetched_pages" not in db.table_names():
        return "[]"

    # Search inside titles, descriptions, and tags in SQL
    rows = list(
        db.execute_returning_dicts(
            "SELECT * FROM fetched_pages WHERE title LIKE ? OR description LIKE ? OR tags LIKE ?",
            [f"%{query}%", f"%{query}%", f"%{query}%"],
        )
    )

    result = []
    for r in rows:
        try:
            tags = json.loads(r.get("tags") or "[]")
        except Exception:
            tags = []
        result.append(
            {
                "title": r.get("title") or r.get("url"),
                "url": r.get("url"),
                "tags": tags,
                "description_snippet": (r.get("description") or "")[:200],
            }
        )
    return json.dumps(result, indent=2)


@mcp.tool()
def get_similar_articles(url: str) -> str:
    """Finds articles in the Knowledge Base that are semantically similar to the article at the specified URL using embeddings.

    Args:
        url (str): The URL of the target article.

    Returns:
        str: JSON list of similar articles with similarity percentages.
    """
    from .server import get_similar_articles as fetch_similar, _get_db as server_db

    db = server_db()
    similar = fetch_similar(db, url)
    return json.dumps(similar, indent=2)
