"""
Model Context Protocol (MCP) Server for the Knowledge Base Web Importer.
Exposes tools for agents to search and query local wiki articles across PostgreSQL and SQLite.
"""

import json
from typing import List, Dict, Any
from mcp.server.fastmcp import FastMCP
from .config import Config
from .base import db_session
from .models_orm import FetchedPage
from .utils import get_similar_articles as fetch_similar

# Load configurations
config = Config()
mcp = FastMCP("KB Web")


@mcp.tool()
def list_articles(limit: int = 100) -> str:
    """Lists saved articles in the Knowledge Base with their URL, title, tags, and fetch timestamp.

    Args:
        limit (int): Maximum number of articles to return (default: 100).

    Returns:
        str: JSON formatted string containing list of articles.
    """
    try:
        with db_session() as session:
            rows = (
                session.query(FetchedPage)
                .order_by(FetchedPage.fetched_at.desc())
                .limit(limit)
                .all()
            )
            if not rows:
                return "No articles found in Knowledge Base."

            result = []
            for r in rows:
                try:
                    tags = json.loads(r.tags or "[]")
                except Exception:
                    tags = []
                result.append(
                    {
                        "title": r.title or r.url,
                        "url": r.url,
                        "tags": tags,
                        "fetched_at": r.fetched_at,
                    }
                )
            return json.dumps(result, indent=2)
    except Exception as e:
        return f"Error listing articles: {e}"


@mcp.tool()
def get_article(url: str) -> str:
    """Retrieves the full details of a specific article by its URL, including its wiki description and tags.

    Args:
        url (str): The primary URL of the article to retrieve.

    Returns:
        str: JSON formatted string containing detailed article metadata.
    """
    try:
        with db_session() as session:
            row = session.query(FetchedPage).filter_by(url=url).first()
            if not row:
                return f"Article with URL '{url}' not found in Knowledge Base."

            try:
                tags = json.loads(row.tags or "[]")
            except Exception:
                tags = []

            return json.dumps(
                {
                    "url": row.url,
                    "title": row.title,
                    "description": row.description,  # wiki summary
                    "tags": tags,
                    "fetched_at": row.fetched_at,
                    "md_content_preview": (row.md_content or "")[:2000],
                },
                indent=2,
            )
    except Exception as e:
        return f"Error retrieving article '{url}': {e}"


@mcp.tool()
def search_articles(query: str, limit: int = 50) -> str:
    """Searches for articles in the Knowledge Base matching the query string in their title, description, or tags.

    Args:
        query (str): The search phrase or keyword to match.
        limit (int): Maximum number of matches to return (default: 50).

    Returns:
        str: JSON formatted list of matching articles.
    """
    try:
        with db_session() as session:
            pattern = f"%{query}%"
            rows = (
                session.query(FetchedPage)
                .filter(
                    (FetchedPage.title.ilike(pattern))
                    | (FetchedPage.description.ilike(pattern))
                    | (FetchedPage.tags.ilike(pattern))
                )
                .limit(limit)
                .all()
            )

            result = []
            for r in rows:
                try:
                    tags = json.loads(r.tags or "[]")
                except Exception:
                    tags = []
                result.append(
                    {
                        "title": r.title or r.url,
                        "url": r.url,
                        "tags": tags,
                        "description_snippet": (r.description or "")[:200],
                    }
                )
            return json.dumps(result, indent=2)
    except Exception as e:
        return f"Error searching articles for '{query}': {e}"


@mcp.tool()
def get_similar_articles(url: str, limit: int = 5) -> str:
    """Finds articles in the Knowledge Base semantically similar to the article at the specified URL using embeddings.

    Args:
        url (str): The URL of the target article.
        limit (int): Number of similar articles to return (default: 5).

    Returns:
        str: JSON list of similar articles with similarity percentages.
    """
    try:
        similar = fetch_similar(None, url, config=config, limit=limit)
        return json.dumps(similar, indent=2)
    except Exception as e:
        return f"Error retrieving similar articles for '{url}': {e}"
