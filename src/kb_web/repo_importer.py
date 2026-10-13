"""
Repository Importer Engine.
Extracts logic from devtul's 'dt rpr' (representation) and 'rpr clone' commands
to shallow clone Git repositories or inspect source folders, generate structured
Markdown articles with Git tables, ASCII directory trees, and code blocks,
and index them directly into the Knowledge Base RAG pipeline.
"""

from datetime import datetime
import fnmatch
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from .base import db_session
from .models_orm import FetchedPage


# Language mapping for fenced code blocks
SYNTAX_MAPPING = {
    ".py": "python",
    ".pyw": "python",
    ".rs": "rust",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".html": "html",
    ".htm": "html",
    ".css": "css",
    ".scss": "scss",
    ".sass": "sass",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".sql": "sql",
    ".sh": "bash",
    ".bash": "bash",
    ".zsh": "bash",
    ".ps1": "powershell",
    ".go": "go",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".hpp": "cpp",
    ".cs": "csharp",
    ".java": "java",
    ".kt": "kotlin",
    ".rb": "ruby",
    ".php": "php",
    ".lua": "lua",
    ".md": "markdown",
    ".txt": "text",
    ".xml": "xml",
    ".svg": "xml",
    ".ini": "ini",
    ".cfg": "ini",
    ".conf": "ini",
    ".dockerfile": "dockerfile",
    "dockerfile": "dockerfile",
}

DEFAULT_IGNORE_PARTS = [
    ".git",
    ".hg",
    ".svn",
    "node_modules",
    "__pycache__",
    ".idea",
    ".vscode",
    ".tox",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".venv",
    "venv",
    "dist",
    "build",
    "target",
    "bin",
    "obj",
    ".eggs",
    ".artifacts",
]

DEFAULT_IGNORE_EXTENSIONS = [
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".svg",
    ".pdf", ".docx", ".xlsx", ".pptx", ".zip", ".tar", ".gz", ".7z",
    ".exe", ".dll", ".so", ".dylib", ".bin", ".whl", ".pyc", ".pyo",
    ".mp3", ".mp4", ".wav", ".avi", ".mov", ".mkv", ".sqlite", ".db"
]


def normalize_repo_url(url: str) -> Tuple[str, str]:
    """
    Normalizes a repository URL and extracts a human-readable title.
    Returns (canonical_url, title).
    """
    clean_url = url.strip()
    if clean_url.endswith(".git"):
        clean_url = clean_url[:-4]

    # Extract owner/repo
    m = re.search(r"github\.com[/:]([\w.-]+)/([\w.-]+)", clean_url, re.IGNORECASE)
    if m:
        owner, repo = m.group(1), m.group(2)
        canonical_url = f"repo://github.com/{owner}/{repo}"
        title = f"{owner}/{repo}"
        return canonical_url, title

    m_gitlab = re.search(r"gitlab\.com[/:]([\w.-]+)/([\w.-]+)", clean_url, re.IGNORECASE)
    if m_gitlab:
        owner, repo = m_gitlab.group(1), m_gitlab.group(2)
        canonical_url = f"repo://gitlab.com/{owner}/{repo}"
        title = f"{owner}/{repo}"
        return canonical_url, title

    # Fallback to last path segment
    parts = [p for p in clean_url.split("/") if p]
    slug = parts[-1] if parts else "repo"
    canonical_url = f"repo://{clean_url}"
    return canonical_url, slug


def get_git_metadata_dict(repo_path: Path) -> Dict[str, Any]:
    """Extracts git metadata using git CLI commands."""
    metadata = {
        "current_branch": "unknown",
        "latest_commit_hash": "",
        "latest_commit_msg": "",
        "author": "",
        "date": "",
        "remotes": "",
        "total_commits": 0,
    }
    shell = os.name == "nt"

    try:
        res = subprocess.run(
            ["git", "-C", str(repo_path), "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, check=True, shell=shell
        )
        metadata["current_branch"] = res.stdout.strip()
    except Exception:
        pass

    try:
        res = subprocess.run(
            ["git", "-C", str(repo_path), "log", "-1", "--format=%h|%s|%an|%cI"],
            capture_output=True, text=True, check=True, shell=shell
        )
        parts = res.stdout.strip().split("|")
        if len(parts) >= 4:
            metadata["latest_commit_hash"] = parts[0]
            metadata["latest_commit_msg"] = parts[1]
            metadata["author"] = parts[2]
            metadata["date"] = parts[3]
    except Exception:
        pass

    try:
        res = subprocess.run(
            ["git", "-C", str(repo_path), "remote", "get-url", "origin"],
            capture_output=True, text=True, check=True, shell=shell
        )
        metadata["remotes"] = res.stdout.strip()
    except Exception:
        pass

    try:
        res = subprocess.run(
            ["git", "-C", str(repo_path), "rev-list", "--count", "HEAD"],
            capture_output=True, text=True, check=True, shell=shell
        )
        metadata["total_commits"] = int(res.stdout.strip() or "0")
    except Exception:
        pass

    return metadata


def build_ascii_tree(files: List[str], parent_name: str = ".") -> str:
    """
    Renders an ASCII directory tree hierarchy matching devtul's build_tree_structure.
    """
    if not files:
        return ""

    tree_dict: Dict[str, Any] = {}
    for file_path in sorted(files):
        parts = [p for p in re.split(r"[\\/]", file_path) if p]
        current = tree_dict
        for i, part in enumerate(parts):
            if i == len(parts) - 1:
                if "__files__" not in current:
                    current["__files__"] = []
                current["__files__"].append(part)
            else:
                if part not in current:
                    current[part] = {}
                current = current[part]

    def render_tree(node: dict, prefix: str = "") -> List[str]:
        lines = []
        dirs = [(k, v) for k, v in node.items() if k != "__files__" and isinstance(v, dict)]
        dirs.sort(key=lambda x: x[0])
        file_list = sorted(node.get("__files__", []))

        all_items = [(name, "dir", content) for name, content in dirs] + [
            (name, "file", None) for name in file_list
        ]

        for i, (name, item_type, content) in enumerate(all_items):
            is_last = (i == len(all_items) - 1)
            symbol = "└── " if is_last else "├── "
            if item_type == "dir":
                lines.append(f"{prefix}{symbol}{name}/")
                next_prefix = prefix + ("    " if is_last else "│   ")
                lines.extend(render_tree(content, next_prefix))
            else:
                lines.append(f"{prefix}{symbol}{name}")

        return lines

    tree_lines = [f"{parent_name}/"] + render_tree(tree_dict)
    return "\n".join(tree_lines)


def get_markdown_syntax(file_path: Path) -> str:
    """Returns the codeblock syntax label for the given file extension."""
    suffix = file_path.suffix.lower()
    return SYNTAX_MAPPING.get(suffix, SYNTAX_MAPPING.get(file_path.name.lower(), "text"))


def should_ignore_path(
    path: Path,
    root: Path,
    match_patterns: Optional[List[str]] = None,
    exclude_patterns: Optional[List[str]] = None,
) -> bool:
    """Checks if a file should be ignored based on default parts, extensions, and custom filters."""
    rel = path.relative_to(root)
    rel_posix = rel.as_posix()

    # Check ignored path parts
    for part in rel.parts:
        if part in DEFAULT_IGNORE_PARTS:
            return True

    # Check binary extensions
    if path.suffix.lower() in DEFAULT_IGNORE_EXTENSIONS:
        return True

    # Check custom excludes
    if exclude_patterns:
        for exc in exclude_patterns:
            if fnmatch.fnmatch(rel_posix, exc) or fnmatch.fnmatch(path.name, exc):
                return True

    # Check custom matches (if given, file must match at least one)
    if match_patterns:
        matched = False
        for m in match_patterns:
            if fnmatch.fnmatch(rel_posix, m) or fnmatch.fnmatch(path.name, m):
                matched = True
                break
        if not matched:
            return True

    return False


def build_repo_markdown_repr(
    repo_path: Path,
    repo_url: str = "",
    match_patterns: Optional[List[str]] = None,
    exclude_patterns: Optional[List[str]] = None,
    max_file_size_bytes: int = 500_000,
) -> Tuple[str, Dict[str, Any]]:
    """
    Synthesizes the complete Markdown representation of a repository matching devtul's dt rpr.
    Returns (markdown_text, metrics_dict).
    """
    resolved_root = repo_path.resolve()
    git_meta = get_git_metadata_dict(resolved_root)
    repo_name = resolved_root.name.upper()

    # Discover and filter files
    included_files: List[Path] = []
    total_scanned = 0
    languages_detected = set()

    for dirpath, dirnames, filenames in os.walk(resolved_root):
        # Filter dirnames in-place to prune deep ignored directories
        dirnames[:] = [d for d in dirnames if d not in DEFAULT_IGNORE_PARTS]

        for fname in filenames:
            total_scanned += 1
            fpath = Path(dirpath) / fname
            if not should_ignore_path(fpath, resolved_root, match_patterns, exclude_patterns):
                included_files.append(fpath)
                syntax = get_markdown_syntax(fpath)
                if syntax not in ("text", "ini"):
                    languages_detected.add(syntax)

    included_files.sort(key=lambda p: p.relative_to(resolved_root).as_posix())
    rel_paths = [p.relative_to(resolved_root).as_posix() for p in included_files]

    # 1. Frontmatter
    now_iso = datetime.now().isoformat()
    lines = [
        "---",
        f"generated_at: '{now_iso}'",
        f"repo_url: '{repo_url}'",
        f"repo_path: '{resolved_root.as_posix()}'",
        f"file_count: {total_scanned}",
        f"files_included: {len(included_files)}",
        f"languages: {list(languages_detected)}",
        "---",
        "",
        f"# {repo_name}",
        "",
        "---",
        "",
    ]

    # 2. Git Metadata Table
    if git_meta.get("latest_commit_hash") or git_meta.get("current_branch") != "unknown":
        lines.extend([
            "## Git Metadata",
            "",
            "| Property | Value |",
            "|---|---|",
            f"| Current Branch | `{git_meta.get('current_branch', 'unknown')}` |",
            f"| Latest Commit | `{git_meta.get('latest_commit_hash', 'N/A')}` |",
            f"| Commit Message | {git_meta.get('latest_commit_msg', 'N/A')} |",
            f"| Author | {git_meta.get('author', 'N/A')} |",
            f"| Date | {git_meta.get('date', 'N/A')} |",
            f"| Remote URL | {git_meta.get('remotes', repo_url)} |",
            f"| Total Commits | {git_meta.get('total_commits', 0)} |",
            "",
            "---",
            "",
        ])

    # 3. Structure
    tree_ascii = build_ascii_tree(rel_paths, parent_name=resolved_root.name)
    lines.extend([
        "## Structure",
        "",
        "```",
        tree_ascii,
        "```",
        "",
        "---",
        "",
        "## Files",
        "",
    ])

    # 4. Files with Metadata and Code blocks
    for fpath in included_files:
        rel_posix = fpath.relative_to(resolved_root).as_posix()
        stat = fpath.stat()
        file_size = stat.st_size
        modified_at = datetime.fromtimestamp(stat.st_mtime).isoformat()
        syntax = get_markdown_syntax(fpath)

        lines.extend([
            f"### `{rel_posix}`",
            "",
            "| Property | Value |",
            "|---|---|",
            f"| Relative Path | `{rel_posix}` |",
            f"| Size | {file_size} bytes |",
            f"| Last Modified | {modified_at} |",
            f"| Language | `{syntax}` |",
            "",
            "**Content**:",
            "",
            f"```{syntax}",
        ])

        if file_size > max_file_size_bytes:
            lines.append(f"// [File truncated: size {file_size} bytes exceeds maximum preview threshold of {max_file_size_bytes} bytes]")
        else:
            try:
                content = fpath.read_text(encoding="utf-8", errors="replace")
                lines.append(content)
            except Exception as e:
                lines.append(f"// Error reading file content: {e}")

        lines.extend([
            "```",
            "",
            "---",
            "",
        ])

    markdown_output = "\n".join(lines)
    metrics = {
        "total_scanned": total_scanned,
        "files_included": len(included_files),
        "languages": sorted(list(languages_detected)),
        "git_meta": git_meta,
    }
    return markdown_output, metrics


def import_git_repo(
    repo_url: str,
    depth: int = 1,
    match_patterns: Optional[List[str]] = None,
    exclude_patterns: Optional[List[str]] = None,
    collection_id: Optional[int] = None,
    session: Optional[Session] = None,
    client: Optional[Any] = None,
) -> FetchedPage:
    """
    Shallow clones a Git repository, generates its Markdown representation using
    devtul's Rpr pipeline, persists the resulting article in fetched_pages,
    and indexes chunks into the RAG vector store.
    """
    canonical_url, repo_title = normalize_repo_url(repo_url)
    shell = os.name == "nt"

    with tempfile.TemporaryDirectory(prefix="kb_repo_clone_") as temp_dir:
        clone_path = Path(temp_dir) / "checkout"
        clone_path.mkdir(parents=True, exist_ok=True)

        clone_cmd = ["git", "clone", "--depth", str(depth), repo_url, str(clone_path)]
        res = subprocess.run(clone_cmd, capture_output=True, text=True, shell=shell)
        if res.returncode != 0:
            raise RuntimeError(f"Failed to clone repository '{repo_url}': {res.stderr.strip() or res.stdout.strip()}")

        # Build representation
        md_text, metrics = build_repo_markdown_repr(
            repo_path=clone_path,
            repo_url=repo_url,
            match_patterns=match_patterns,
            exclude_patterns=exclude_patterns,
        )

        now_str = datetime.now().isoformat()
        languages_str = ", ".join(metrics.get("languages", []))
        tags = f"repo, git, {languages_str}".strip(", ")
        desc = f"Git repository representation: {repo_url} ({metrics.get('files_included', 0)} files, branch: {metrics.get('git_meta', {}).get('current_branch', 'HEAD')})"

        # Persist to database
        def _save(s: Session) -> FetchedPage:
            page = s.query(FetchedPage).filter_by(url=canonical_url).first()
            if not page:
                page = FetchedPage(
                    url=canonical_url,
                    title=repo_title,
                    description=desc,
                    tags=tags,
                    html_content="",
                    md_content=md_text,
                    collection_id=collection_id,
                    fetched_at=now_str,
                    is_frozen=0,
                )
                s.add(page)
            else:
                page.title = repo_title
                page.description = desc
                page.tags = tags
                page.md_content = md_text
                page.fetched_at = now_str
                if collection_id is not None:
                    page.collection_id = collection_id

            s.commit()
            s.refresh(page)
            return page

        if session:
            saved_page = _save(session)
        else:
            with db_session() as s:
                saved_page = _save(s)

    # Trigger chunk embedding generation so the repo is immediately queryable in RAG
    try:
        from .utils import generate_gemma_embeddings_for_page
        generate_gemma_embeddings_for_page(saved_page.url, client=client)
    except Exception as e:
        print(f"[WARN] Failed generating vector chunk embeddings for repo {canonical_url}: {e}")

    return saved_page
