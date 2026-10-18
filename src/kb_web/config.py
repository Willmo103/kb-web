"""
Configuration for the kb-web application.
"""

from pathlib import Path
import base64
import hashlib
import hmac
import json
import os
import secrets
import sys
from typing import Any, Dict, List, Optional, Tuple

from kb_core.config import Config as BaseConfig
from kb_core.notifier import Gotify
from dotenv import load_dotenv

INSECURE_DEFAULT_API_KEY = "kb-secret-key"
INSECURE_DEFAULT_PASSWORD = "admin123"
DEFAULT_TRUSTED_PROXIES = "127.0.0.1, ::1"


def hash_password(password: str) -> str:
    """Hashes a password using scrypt with a cryptographically random 16-byte salt."""
    salt = secrets.token_bytes(16)
    hashed = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=16384, r=8, p=1)
    salt_b64 = base64.b64encode(salt).decode("ascii")
    hash_b64 = base64.b64encode(hashed).decode("ascii")
    return f"scrypt${salt_b64}${hash_b64}"


def verify_password(plain_password: str, stored_hash_or_plain: str) -> Tuple[bool, bool]:
    """Verifies plain_password against stored_hash_or_plain.

    Returns (is_valid, needs_migration).
    """
    if not stored_hash_or_plain or not plain_password:
        return False, False
    if stored_hash_or_plain.startswith("scrypt$"):
        try:
            parts = stored_hash_or_plain.split("$")
            if len(parts) == 3:
                salt = base64.b64decode(parts[1])
                expected = base64.b64decode(parts[2])
                calc = hashlib.scrypt(
                    plain_password.encode("utf-8"), salt=salt, n=16384, r=8, p=1
                )
                return hmac.compare_digest(calc, expected), False
        except Exception:
            return False, False
    # Backward compatibility with plaintext
    try:
        if hmac.compare_digest(plain_password, stored_hash_or_plain):
            return True, True
    except Exception:
        pass
    return False, False


ROOT_DIR = Path(__file__).parent.parent.parent
ENV_FILE = ROOT_DIR / ".env"

_msg_printed = False
ENV_LOADED = load_dotenv(ENV_FILE)
if ENV_LOADED and not _msg_printed:
    print(f"✅ Environment variables loaded from {ENV_FILE}")
    _msg_printed = True
elif not ENV_LOADED and not _msg_printed:
    print(f"⚠️ Environment variables not loaded from {ENV_FILE}")
    _msg_printed = True

DEFAULT_WIKI_PROMPT = (
    "You are an expert knowledge-base engineer. Extract the core informational content "
    "from the provided web page markdown and rewrite it as a clean, highly structured, "
    "and objective wiki entry. The entry MUST start with a markdown header level 1 (#) representing "
    "a descriptive and clear title for the page (e.g. '# Quickstart Guide for Python'). "
    "Strip out all ads, clickbait, sidebars, navigation links, cookie banners, "
    "and user comments. Keep only the valuable data, analysis, code blocks, or technical tutorials. "
    "Output ONLY the final markdown text. Do not reply with conversational filler headers."
)

DEFAULT_YOUTUBE_DOWNLOAD_FORMAT = (
    "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/bv*+ba/b"
)

DEFAULT_YOUTUBE_WIKI_PROMPT = (
    "You are an expert knowledge-base agent. Analyze the provided YouTube video transcript and metadata. "
    "Rewrite it as a clean, highly structured, and objective wiki article. "
    "The article MUST start with a markdown header level 1 (#) representing a descriptive and clear title for the video. "
    "Create appropriate sections with headings, tags, and a summary. "
    "CRITICAL: You MUST include a detailed 'Video Breakdown' section. Under this section, segment the video chronologically "
    "into logical chapters or topics based on the transcript timestamps (e.g. '[03:15]'). "
    "For EACH section, provide a brief description and at least two key quoted points or insights from the transcript, "
    "including the exact timestamp of each quote. "
    "Format the timestamps precisely as they appear in the transcript (e.g., [MM:SS] or [HH:MM:SS]). "
    "Output ONLY the final markdown text. Do not reply with conversational filler."
)

DEFAULT_RAG_SYSTEM_PROMPT = (
    "You are a helpful knowledge assistant for this collection. "
    "Use the provided context to answer the user's questions accurately, structured, and objectively. "
    "If the answer cannot be found in the context, clearly state that."
)

DEFAULT_TAXONOMY_SYSTEM_PROMPT = (
    "You are an expert taxonomist. Analyze the incoming document details (URL, title, description, tags) "
    "and categorize it into a virtual filetree system representing the General Collection of all knowledge. "
    "To avoid duplicate folder structures and keep the tree organized, here is the current taxonomy tree:\n"
    "{{taxonomy_tree_str}}\n\n"
    "Output ONLY a valid JSON object matching the format:\n"
    '{"taxonomy_path": "/Folder/Subfolder/Filename.md", "action_note": "A short, 1-sentence description of what this note contains."}'
)

DEFAULT_TAGS_PROMPT = (
    "You are a professional categorization assistant. Analyze the following web page content "
    "and generate a list of 5 to 10 relevant tags, keywords, or labels for cataloging it. "
    "Respond ONLY with a comma-separated list of tags (e.g., 'python, web-development, tutorial'). "
    "Do not reply with any filler headers, introductory remarks, or formatting."
)

DEFAULT_RAG_REPORT_PROMPT = (
    "You are the expert Senior Research & Synthesis Agent for kb-web.\n"
    "Your task is to analyze the user's research query and synthesize the provided vetted evidence "
    "into a comprehensive, publication-grade Markdown research report.\n\n"
    "Structure your output strictly using the following Markdown sections:\n"
    "# [Concise, Descriptive Report Title]\n\n"
    "## Executive Summary\n"
    "[A clear, synthesized overview directly answering the query]\n\n"
    "## Key Findings & Core Insights\n"
    "[Detailed, bulleted breakdown of actionable facts and architectural insights]\n\n"
    "## Technical Architecture & Code Examples\n"
    "[Concrete code snippets, configuration rules, SQL queries, or commands extracted from evidence]\n\n"
    "## Evidence & Citations Table\n"
    "| # | Source Title | Channel | Decision Score | URL |\n"
    "|---|---|---|---|---|\n"
    "[Fill table rows based on sources provided]\n\n"
    "Do not invent false details. If certain specifics are not covered in the evidence, state so clearly."
)

DEFAULT_MAINTENANCE_AGENT_PROMPT = (
    "You are the kb-web Site Maintenance Agent. You provide immediate, accurate root cause "
    "diagnostics and precise code/database fixes for uncaught server errors.\n"
    "Structure your response with:\n"
    "1. 🔍 Root Cause Analysis (what broke and why)\n"
    "2. 📍 Affected Component / Source Location\n"
    "3. 🛠️ Actionable Recommended Fix (exact SQL or Python code change required)"
)

DEFAULT_WORKSPACE_AGENT_PROMPT = (
    "You are an expert autonomous coding assistant for the workspace.\n"
    "You can inspect, create, and edit files, and plan architectural implementations. "
    "Explain your plan concisely and invoke tools accurately."
)

DEFAULT_ARTICLE_CHAT_PROMPT = (
    "You are an expert AI knowledge-base assistant. Answer the user's questions accurately, "
    "helpfully, and concisely based on the document context provided below."
)

DEFAULT_ONTOLOGY_SYNTHESIS_PROMPT = (
    "You are an authoritative ontologist and knowledge domain architect. "
    "Synthesize a clear domain classification and wiki description for the provided subject.\n"
    "Respond with a valid JSON object containing 'category_name' and 'category_doc' fields."
)


class Config:
    """Configuration class for the kb-web application.

    Inherits from the base kb-core Config class and adds properties for
    managing the Ollama host/model, administrative UI password, Gotify
    notification parameters, wiki system prompts, and browser extension API keys.
    Supports parsing from a config file (kb-web.json) or falling back to
    environment variables.
    """

    data_root: Path = Path().home() / ".kb"
    configs_dir: Path = data_root / "configs"
    backups_dir: Path = data_root / "kb-web_backups"
    db_path: Path = data_root / "kb.db"

    def __init__(self) -> None:
        """Initializes configuration properties with default values and overlays

        from the config file (~/.kb/configs/kb-web.json) or environment variables.
        """
        # 1. Apply defaults or environment variables first
        self._ollama_host: str = os.getenv("KB_OLLAMA_HOST", "http://localhost:11434")
        self._ollama_model: str = os.getenv("KB_OLLAMA_MODEL", "gemma4:latest")
        self._ollama_embedding_model: str = os.getenv(
            "KB_OLLAMA_EMBEDDING_MODEL", "nomic-embed-text"
        )
        self._admin_password: str = os.getenv("KB_PASSWORD", "admin123")
        self._api_key: Optional[str] = os.getenv("KB_API_KEY", "kb-secret-key")
        self._wiki_prompt: str = os.getenv("KB_WIKI_PROMPT", DEFAULT_WIKI_PROMPT)
        self._youtube_wiki_prompt: str = os.getenv(
            "KB_YOUTUBE_WIKI_PROMPT", DEFAULT_YOUTUBE_WIKI_PROMPT
        )
        self._tags_prompt: str = os.getenv("KB_TAGS_PROMPT", DEFAULT_TAGS_PROMPT)
        self._rag_system_prompt: str = os.getenv("KB_RAG_SYSTEM_PROMPT", DEFAULT_RAG_SYSTEM_PROMPT)
        self._taxonomy_system_prompt: str = os.getenv("KB_TAXONOMY_SYSTEM_PROMPT", DEFAULT_TAXONOMY_SYSTEM_PROMPT)
        self._rag_report_prompt: str = os.getenv("KB_RAG_REPORT_PROMPT", DEFAULT_RAG_REPORT_PROMPT)
        self._maintenance_agent_prompt: str = os.getenv("KB_MAINTENANCE_AGENT_PROMPT", DEFAULT_MAINTENANCE_AGENT_PROMPT)
        self._workspace_agent_prompt: str = os.getenv("KB_WORKSPACE_AGENT_PROMPT", DEFAULT_WORKSPACE_AGENT_PROMPT)
        self._article_chat_prompt: str = os.getenv("KB_ARTICLE_CHAT_PROMPT", DEFAULT_ARTICLE_CHAT_PROMPT)
        self._ontology_synthesis_prompt: str = os.getenv("KB_ONTOLOGY_SYNTHESIS_PROMPT", DEFAULT_ONTOLOGY_SYNTHESIS_PROMPT)
        self._similarity_threshold: float = float(
            os.getenv("KB_SIMILARITY_THRESHOLD", "0.8")
        )
        self._max_input_length: int = int(os.getenv("KB_MAX_INPUT_LENGTH", "20000"))
        self._ollama_timeout: float = float(os.getenv("KB_OLLAMA_TIMEOUT", "1200.0"))
        self._ollama_think: bool = os.getenv("KB_OLLAMA_THINK", "false").lower() in (
            "true",
            "1",
        )
        self._gotify_url: Optional[str] = os.getenv("GOTIFY_URL")
        self._gotify_token: Optional[str] = os.getenv("GOTIFY_TOKEN")
        self._qdrant_host_url: Optional[str] = os.getenv("QDRANT_HOST_URL")
        self._qdrant_api_key: Optional[str] = os.getenv("QDRANT_API_KEY")
        self._database_url: str = os.getenv("DATABASE_URL", "")
        self._trusted_proxies: str = os.getenv("KB_TRUSTED_PROXIES", DEFAULT_TRUSTED_PROXIES)
        self._session_secret: Optional[str] = os.getenv("KB_SESSION_SECRET")
        self._admin_password_hash: Optional[str] = None

    def get_db(self):
        """Returns a sqlite_utils Database connection for the configured SQLite database."""
        from .db import get_db

        return get_db(self)

    @property
    def _settings_cache_file(self) -> Path:
        """Returns the path to the persistent settings cache file."""
        self.configs_dir.mkdir(parents=True, exist_ok=True)
        return self.configs_dir / "db_settings_cache.json"

    def _read_cached_setting(self, table: str, key: str):
        """Reads a setting from local disk cache if database is recovering or unreachable."""
        try:
            cache_file = self._settings_cache_file
            if cache_file.exists():
                with open(cache_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return data.get(f"{table}:{key}")
        except Exception:
            pass
        return None

    def _write_cached_setting(self, table: str, key: str, value) -> None:
        """Persists a setting to local disk cache for instant recovery upon power loss or reboot."""
        try:
            cache_file = self._settings_cache_file
            data = {}
            if cache_file.exists():
                try:
                    with open(cache_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                except Exception:
                    data = {}
            data[f"{table}:{key}"] = str(value)
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception:
            pass

    def _read_db_setting(self, table: str, key: str, default):
        if self.database_url and (
            "postgresql" in self.database_url or "postgres" in self.database_url
        ):
            try:
                from .models_orm import SettingOllama, SettingExternal
                from .base import db_session

                with db_session() as session:
                    if table == "settings_ollama":
                        row = session.query(SettingOllama).filter_by(key=key).first()
                    elif table == "settings_external":
                        row = session.query(SettingExternal).filter_by(key=key).first()
                    else:
                        row = None

                    if row and row.value is not None:
                        val = row.value
                        self._write_cached_setting(table, key, val)
                        if isinstance(default, bool):
                            return val.lower() in ("true", "1")
                        if isinstance(default, int):
                            return int(val)
                        if isinstance(default, float):
                            return float(val)
                        return val
            except Exception as e:
                print(f"Error reading DB setting from PostgreSQL: {e}")
                # Fallback to local disk cache before reverting to default factory credentials
                cached = self._read_cached_setting(table, key)
                if cached is not None:
                    if isinstance(default, bool):
                        return cached.lower() in ("true", "1")
                    if isinstance(default, int):
                        return int(cached)
                    if isinstance(default, float):
                        return float(cached)
                    return cached
            return default

        try:
            from .db import get_db

            db = get_db(self)
            if table in db.table_names():
                row = db[table].get(key)
                if row and row.get("value") is not None:
                    val = row["value"]
                    self._write_cached_setting(table, key, val)
                    if isinstance(default, bool):
                        return val.lower() in ("true", "1")
                    if isinstance(default, int):
                        return int(val)
                    if isinstance(default, float):
                        return float(val)
                    return val
        except Exception:
            cached = self._read_cached_setting(table, key)
            if cached is not None:
                if isinstance(default, bool):
                    return cached.lower() in ("true", "1")
                if isinstance(default, int):
                    return int(cached)
                if isinstance(default, float):
                    return float(cached)
                return cached
        return default

    def _write_db_setting(self, table: str, key: str, value) -> None:
        self._write_cached_setting(table, key, value)
        if self.database_url and (
            "postgresql" in self.database_url or "postgres" in self.database_url
        ):
            try:
                from .models_orm import SettingOllama, SettingExternal
                from .base import db_session

                val_str = str(value)
                with db_session() as session:
                    if table == "settings_ollama":
                        row = session.query(SettingOllama).filter_by(key=key).first()
                        if row:
                            row.value = val_str
                        else:
                            session.add(SettingOllama(key=key, value=val_str))
                    elif table == "settings_external":
                        row = session.query(SettingExternal).filter_by(key=key).first()
                        if row:
                            row.value = val_str
                        else:
                            session.add(SettingExternal(key=key, value=val_str))
                return
            except Exception as e:
                print(f"Error writing DB setting to PostgreSQL: {e}")
                return

        try:
            from .db import get_db

            db = get_db(self)
            if table in db.table_names():
                val_str = str(value)
                db[table].upsert({"key": key, "value": val_str}, pk="key")
                db.conn.commit()
        except Exception:
            pass

    def get_database_url_for_target(self, target: str) -> str:
        """Resolves database URL based on environment variables for dev, test, or live."""
        t = target.lower().strip()
        if t in ("dev", "development", "kb_dev"):
            return os.getenv("KB_DEV_DATABASE_URL") or os.getenv("DATABASE_URL", "")
        elif t in ("test", "testing", "kb_test"):
            return os.getenv("KB_TEST_DATABASE_URL") or os.getenv("DATABASE_URL", "")
        elif t in ("live", "prod", "production", "kb_live", "kb_production"):
            return (
                os.getenv("KB_LIVE_DATABASE_URL")
                or os.getenv("KB_PROD_DATABASE_URL")
                or os.getenv("DATABASE_URL", "")
            )
        elif t in ("default", "current", ""):
            return self.database_url or f"sqlite:///{self.db_path}"
        return target


    @property
    def ollama_host(self) -> str:
        return self._read_db_setting(
            "settings_ollama", "ollama_host", self._ollama_host
        )

    @ollama_host.setter
    def ollama_host(self, value: str) -> None:
        self._ollama_host = value
        self._write_db_setting("settings_ollama", "ollama_host", value)

    @property
    def ollama_model(self) -> str:
        return self._read_db_setting(
            "settings_ollama", "ollama_model", self._ollama_model
        )

    @ollama_model.setter
    def ollama_model(self, value: str) -> None:
        self._ollama_model = value
        self._write_db_setting("settings_ollama", "ollama_model", value)

    @property
    def ollama_embedding_model(self) -> str:
        return self._read_db_setting(
            "settings_ollama", "ollama_embedding_model", self._ollama_embedding_model
        )

    @ollama_embedding_model.setter
    def ollama_embedding_model(self, value: str) -> None:
        self._ollama_embedding_model = value
        self._write_db_setting("settings_ollama", "ollama_embedding_model", value)

    @property
    def max_input_length(self) -> int:
        return self._read_db_setting(
            "settings_ollama", "max_input_length", self._max_input_length
        )

    @max_input_length.setter
    def max_input_length(self, value: int) -> None:
        self._max_input_length = value
        self._write_db_setting("settings_ollama", "max_input_length", value)

    @property
    def ollama_think(self) -> bool:
        return self._read_db_setting(
            "settings_ollama", "ollama_think", self._ollama_think
        )

    @ollama_think.setter
    def ollama_think(self, value: bool) -> None:
        self._ollama_think = value
        self._write_db_setting("settings_ollama", "ollama_think", "1" if value else "0")

    @property
    def ollama_timeout(self) -> float:
        val = self._read_db_setting(
            "settings_ollama", "ollama_timeout", str(self._ollama_timeout)
        )
        try:
            return float(val)
        except (ValueError, TypeError):
            return self._ollama_timeout

    @ollama_timeout.setter
    def ollama_timeout(self, value: float) -> None:
        self._ollama_timeout = float(value)
        self._write_db_setting("settings_ollama", "ollama_timeout", str(value))

    @property
    def database_url(self) -> str:
        return self._database_url

    @database_url.setter
    def database_url(self, value: str) -> None:
        self._database_url = value

    @property
    def admin_password(self) -> str:
        return self._read_db_setting(
            "settings_external", "admin_password", self._admin_password
        )

    @admin_password.setter
    def admin_password(self, value: str) -> None:
        self._admin_password = value
        self._write_db_setting("settings_external", "admin_password", value)
        if value:
            if value.startswith("scrypt$"):
                self.admin_password_hash = value
            else:
                self.admin_password_hash = hash_password(value)

    @property
    def api_key(self) -> Optional[str]:
        val = self._read_db_setting("settings_external", "api_key", self._api_key)
        return val if val else None

    @api_key.setter
    def api_key(self, value: Optional[str]) -> None:
        self._api_key = value
        self._write_db_setting("settings_external", "api_key", value or "")

    @property
    def admin_password_hash(self) -> Optional[str]:
        val = self._read_db_setting(
            "settings_external", "admin_password_hash", self._admin_password_hash
        )
        return val if val else None

    @admin_password_hash.setter
    def admin_password_hash(self, value: Optional[str]) -> None:
        self._admin_password_hash = value
        self._write_db_setting("settings_external", "admin_password_hash", value or "")

    @property
    def trusted_proxies(self) -> str:
        return self._read_db_setting(
            "settings_external", "trusted_proxies", self._trusted_proxies
        )

    @trusted_proxies.setter
    def trusted_proxies(self, value: str) -> None:
        self._trusted_proxies = str(value).strip()
        self._write_db_setting("settings_external", "trusted_proxies", self._trusted_proxies)

    @property
    def allow_insecure_defaults(self) -> bool:
        if "pytest" in sys.modules or os.getenv("PYTEST_CURRENT_TEST"):
            return True
        return os.getenv("KB_ALLOW_INSECURE_DEFAULTS", "0").lower() in ("1", "true", "yes")

    @property
    def is_default_password(self) -> bool:
        stored_hash = self.admin_password_hash
        if stored_hash:
            valid, _ = verify_password(INSECURE_DEFAULT_PASSWORD, stored_hash)
            return valid
        stored = self.admin_password
        if stored == INSECURE_DEFAULT_PASSWORD:
            return True
        valid, _ = verify_password(INSECURE_DEFAULT_PASSWORD, stored)
        return valid

    @property
    def is_default_api_key(self) -> bool:
        return (self.api_key or "") == INSECURE_DEFAULT_API_KEY

    @property
    def session_secret(self) -> str:
        """Returns or generates a dedicated cryptographically secure session signing secret."""
        if self._session_secret:
            return self._session_secret
        val = self._read_db_setting("settings_external", "session_secret", None)
        if val:
            self._session_secret = val
            return val
        new_secret = secrets.token_hex(32)
        self._session_secret = new_secret
        self._write_db_setting("settings_external", "session_secret", new_secret)
        return new_secret

    @session_secret.setter
    def session_secret(self, value: str) -> None:
        self._session_secret = value
        self._write_db_setting("settings_external", "session_secret", value)

    @property
    def gotify_url(self) -> Optional[str]:
        val = self._read_db_setting("settings_external", "gotify_url", self._gotify_url)
        return val if val else None

    @gotify_url.setter
    def gotify_url(self, value: Optional[str]) -> None:
        self._gotify_url = value
        self._write_db_setting("settings_external", "gotify_url", value or "")

    @property
    def gotify_token(self) -> Optional[str]:
        val = self._read_db_setting(
            "settings_external", "gotify_token", self._gotify_token
        )
        return val if val else None

    @gotify_token.setter
    def gotify_token(self, value: Optional[str]) -> None:
        self._gotify_token = value
        self._write_db_setting("settings_external", "gotify_token", value or "")

    @property
    def qdrant_host_url(self) -> Optional[str]:
        val = self._read_db_setting(
            "settings_external", "qdrant_host_url", self._qdrant_host_url
        )
        return val if val else None

    @qdrant_host_url.setter
    def qdrant_host_url(self, value: Optional[str]) -> None:
        self._qdrant_host_url = value
        self._write_db_setting("settings_external", "qdrant_host_url", value or "")

    @property
    def qdrant_api_key(self) -> Optional[str]:
        val = self._read_db_setting(
            "settings_external", "qdrant_api_key", self._qdrant_api_key
        )
        return val if val else None

    @qdrant_api_key.setter
    def qdrant_api_key(self, value: Optional[str]) -> None:
        self._qdrant_api_key = value
        self._write_db_setting("settings_external", "qdrant_api_key", value or "")

    def _get_agent_prompt(self, prompt_type: str, fallback: str) -> str:
        """Retrieves active head version of a prompt from PostgreSQL/SQLite or falls back to default."""
        if self.database_url and (
            "postgresql" in self.database_url or "postgres" in self.database_url
        ):
            try:
                from .models_orm import AgentPrompt
                from .base import db_session

                with db_session() as session:
                    row = (
                        session.query(AgentPrompt)
                        .filter_by(prompt_type=prompt_type, is_head=1)
                        .first()
                    )
                    if row and row.prompt_text:
                        return row.prompt_text
            except Exception:
                pass
            return fallback

        try:
            db = self.get_db()
            if "agent_prompts" in db.table_names():
                rows = list(
                    db["agent_prompts"].rows_where(
                        f"prompt_type = '{prompt_type}' AND is_head = 1"
                    )
                )
                if rows and rows[0].get("prompt_text"):
                    return rows[0]["prompt_text"]
        except Exception:
            pass
        return fallback

    def _set_agent_prompt(self, prompt_type: str, value: str) -> None:
        """Persists a new head version of an agent prompt to database."""
        if not value:
            return
        if self.database_url and (
            "postgresql" in self.database_url or "postgres" in self.database_url
        ):
            try:
                from .models_orm import AgentPrompt
                from .base import db_session
                from datetime import datetime
                from sqlalchemy import func

                with db_session() as session:
                    current_head = None
                    row = (
                        session.query(AgentPrompt)
                        .filter_by(prompt_type=prompt_type, is_head=1)
                        .first()
                    )
                    if row:
                        current_head = row.prompt_text

                    if current_head != value:
                        max_version = (
                            session.query(func.max(AgentPrompt.version))
                            .filter_by(prompt_type=prompt_type)
                            .scalar()
                            or 0
                        )
                        session.query(AgentPrompt).filter_by(
                            prompt_type=prompt_type, is_head=1
                        ).update({"is_head": 0})
                        session.add(
                            AgentPrompt(
                                prompt_type=prompt_type,
                                prompt_text=value,
                                is_head=1,
                                version=max_version + 1,
                                created_at=datetime.now().isoformat(),
                            )
                        )
                        session.commit()
                return
            except Exception as e:
                print(f"Error setting {prompt_type} on PostgreSQL: {e}")
                return

        try:
            db = self.get_db()
            if "agent_prompts" in db.table_names():
                current_head = None
                rows = list(
                    db["agent_prompts"].rows_where(
                        f"prompt_type = '{prompt_type}' AND is_head = 1"
                    )
                )
                if rows:
                    current_head = rows[0]["prompt_text"]

                if current_head != value:
                    from datetime import datetime

                    max_version = 0
                    all_versions = list(
                        db.execute_returning_dicts(
                            f"SELECT MAX(version) as mv FROM agent_prompts WHERE prompt_type = '{prompt_type}'"
                        )
                    )
                    if all_versions and all_versions[0]["mv"] is not None:
                        max_version = all_versions[0]["mv"]

                    db.execute(
                        f"UPDATE agent_prompts SET is_head = 0 WHERE prompt_type = '{prompt_type}'"
                    )
                    db["agent_prompts"].insert(
                        {
                            "prompt_type": prompt_type,
                            "prompt_text": value,
                            "is_head": 1,
                            "version": max_version + 1,
                            "created_at": datetime.now().isoformat(),
                        }
                    )
                    db.conn.commit()
        except Exception as e:
            print(f"Error setting {prompt_type}: {e}")

    @property
    def wiki_prompt(self) -> str:
        return self._get_agent_prompt("wiki_prompt", self._wiki_prompt)

    @wiki_prompt.setter
    def wiki_prompt(self, value: str) -> None:
        self._wiki_prompt = value
        self._set_agent_prompt("wiki_prompt", value)

    @property
    def youtube_wiki_prompt(self) -> str:
        return self._get_agent_prompt("youtube_wiki_prompt", self._youtube_wiki_prompt)

    @youtube_wiki_prompt.setter
    def youtube_wiki_prompt(self, value: str) -> None:
        self._youtube_wiki_prompt = value
        self._set_agent_prompt("youtube_wiki_prompt", value)

    @property
    def tags_prompt(self) -> str:
        return self._get_agent_prompt("tags_prompt", self._tags_prompt)

    @tags_prompt.setter
    def tags_prompt(self, value: str) -> None:
        self._tags_prompt = value
        self._set_agent_prompt("tags_prompt", value)

    @property
    def rag_system_prompt(self) -> str:
        return self._get_agent_prompt("rag_system_prompt", self._rag_system_prompt)

    @rag_system_prompt.setter
    def rag_system_prompt(self, value: str) -> None:
        self._rag_system_prompt = value
        self._set_agent_prompt("rag_system_prompt", value)

    @property
    def taxonomy_system_prompt(self) -> str:
        return self._get_agent_prompt("taxonomy_system_prompt", self._taxonomy_system_prompt)

    @taxonomy_system_prompt.setter
    def taxonomy_system_prompt(self, value: str) -> None:
        self._taxonomy_system_prompt = value
        self._set_agent_prompt("taxonomy_system_prompt", value)

    @property
    def rag_report_prompt(self) -> str:
        return self._get_agent_prompt("rag_report_prompt", self._rag_report_prompt)

    @rag_report_prompt.setter
    def rag_report_prompt(self, value: str) -> None:
        self._rag_report_prompt = value
        self._set_agent_prompt("rag_report_prompt", value)

    @property
    def maintenance_agent_prompt(self) -> str:
        return self._get_agent_prompt("maintenance_agent_prompt", self._maintenance_agent_prompt)

    @maintenance_agent_prompt.setter
    def maintenance_agent_prompt(self, value: str) -> None:
        self._maintenance_agent_prompt = value
        self._set_agent_prompt("maintenance_agent_prompt", value)

    @property
    def workspace_agent_prompt(self) -> str:
        return self._get_agent_prompt("workspace_agent_prompt", self._workspace_agent_prompt)

    @workspace_agent_prompt.setter
    def workspace_agent_prompt(self, value: str) -> None:
        self._workspace_agent_prompt = value
        self._set_agent_prompt("workspace_agent_prompt", value)

    @property
    def article_chat_prompt(self) -> str:
        return self._get_agent_prompt("article_chat_prompt", self._article_chat_prompt)

    @article_chat_prompt.setter
    def article_chat_prompt(self, value: str) -> None:
        self._article_chat_prompt = value
        self._set_agent_prompt("article_chat_prompt", value)

    @property
    def ontology_synthesis_prompt(self) -> str:
        return self._get_agent_prompt("ontology_synthesis_prompt", self._ontology_synthesis_prompt)

    @ontology_synthesis_prompt.setter
    def ontology_synthesis_prompt(self, value: str) -> None:
        self._ontology_synthesis_prompt = value
        self._set_agent_prompt("ontology_synthesis_prompt", value)

    def get_all_prompts(self) -> List[Dict[str, Any]]:
        """Returns metadata and values for all registered system messages and prompts."""
        return [
            {
                "id": "wiki_prompt",
                "name": "Wiki Extraction & Synthesis",
                "label": "Wiki Extraction System Prompt",
                "category": "Curation",
                "description": "Transforms raw scraped web page markdown into structured clean wiki articles.",
                "value": self.wiki_prompt,
                "default": DEFAULT_WIKI_PROMPT,
            },
            {
                "id": "youtube_wiki_prompt",
                "name": "YouTube Video Breakdown",
                "label": "YouTube Wiki System Prompt",
                "category": "Curation",
                "description": "Converts video transcripts into structured articles with chronological timestamps and key quotes.",
                "value": self.youtube_wiki_prompt,
                "default": DEFAULT_YOUTUBE_WIKI_PROMPT,
            },
            {
                "id": "tags_prompt",
                "name": "Tag Taxonomy & Keywords",
                "label": "AI Tag Curation System Prompt",
                "category": "Curation",
                "description": "Analyzes page markdown and extracts 5 to 10 comma-separated categorization tags.",
                "value": self.tags_prompt,
                "default": DEFAULT_TAGS_PROMPT,
            },
            {
                "id": "rag_system_prompt",
                "name": "Collection Knowledge Assistant",
                "label": "Agentic RAG System Instructions",
                "category": "Research & RAG",
                "description": "System instruction for collection-grounded conversational Q&A and factual query answering.",
                "value": self.rag_system_prompt,
                "default": DEFAULT_RAG_SYSTEM_PROMPT,
            },
            {
                "id": "taxonomy_system_prompt",
                "name": "Hierarchical Filetree Taxonomist",
                "label": "Taxonomy Structuring Instructions",
                "category": "Curation",
                "description": "Taxonomy classifier that routes incoming articles into the virtual filetree folders.",
                "value": self.taxonomy_system_prompt,
                "default": DEFAULT_TAXONOMY_SYSTEM_PROMPT,
            },
            {
                "id": "rag_report_prompt",
                "name": "Research Report Synthesis",
                "label": "Research Report Compilation Prompt",
                "category": "Research & RAG",
                "description": "Senior research agent prompt that compiles multi-agent search evidence into publication-grade Markdown reports.",
                "value": self.rag_report_prompt,
                "default": DEFAULT_RAG_REPORT_PROMPT,
            },
            {
                "id": "maintenance_agent_prompt",
                "name": "Site Maintenance Error Diagnostics",
                "label": "Maintenance & Error Diagnostic Prompt",
                "category": "Diagnostics",
                "description": "System prompt for analyzing uncaught server exceptions, inspecting code context, and diagnosing root causes.",
                "value": self.maintenance_agent_prompt,
                "default": DEFAULT_MAINTENANCE_AGENT_PROMPT,
            },
            {
                "id": "workspace_agent_prompt",
                "name": "Workspace Autonomous Coding Assistant",
                "label": "Workspace Coding Assistant Prompt",
                "category": "Coding & Chat",
                "description": "System prompt for in-browser IDE coding agent pairing, file modifications, and planning.",
                "value": self.workspace_agent_prompt,
                "default": DEFAULT_WORKSPACE_AGENT_PROMPT,
            },
            {
                "id": "article_chat_prompt",
                "name": "Article Document Reading Assistant",
                "label": "Article Q&A System Prompt",
                "category": "Coding & Chat",
                "description": "Document-grounded conversational agent for interactive Q&A inside saved articles.",
                "value": self.article_chat_prompt,
                "default": DEFAULT_ARTICLE_CHAT_PROMPT,
            },
            {
                "id": "ontology_synthesis_prompt",
                "name": "Domain Ontology Architect",
                "label": "Domain Ontology Synthesis Prompt",
                "category": "Curation",
                "description": "Autonomous state machine prompt that synthesizes new domain categories and authoritative scope documentation.",
                "value": self.ontology_synthesis_prompt,
                "default": DEFAULT_ONTOLOGY_SYNTHESIS_PROMPT,
            },
        ]

    @property
    def similarity_threshold(self) -> float:
        return self._read_db_setting("settings_ollama", "similarity_threshold", self._similarity_threshold)

    @similarity_threshold.setter
    def similarity_threshold(self, value: float) -> None:
        self._similarity_threshold = float(value)
        self._write_db_setting("settings_ollama", "similarity_threshold", float(value))

    @property
    def ollama_timeout(self) -> float:
        return self._read_db_setting("settings_ollama", "ollama_timeout", self._ollama_timeout)

    @ollama_timeout.setter
    def ollama_timeout(self, value: float) -> None:
        self._ollama_timeout = float(value)
        self._write_db_setting("settings_ollama", "ollama_timeout", float(value))

    @property
    def rag_search_top_k(self) -> int:
        return self._read_db_setting("settings_ollama", "rag_search_top_k", 10)

    @rag_search_top_k.setter
    def rag_search_top_k(self, value: int) -> None:
        self._write_db_setting("settings_ollama", "rag_search_top_k", int(value))

    @property
    def taxonomy_batch_limit(self) -> int:
        return self._read_db_setting("settings_external", "taxonomy_batch_limit", 500)

    @taxonomy_batch_limit.setter
    def taxonomy_batch_limit(self, value: int) -> None:
        self._write_db_setting("settings_external", "taxonomy_batch_limit", int(value))

    @property
    def notifications_poll_interval_seconds(self) -> int:
        return self._read_db_setting("settings_external", "notifications_poll_interval_seconds", 5)

    @notifications_poll_interval_seconds.setter
    def notifications_poll_interval_seconds(self, value: int) -> None:
        self._write_db_setting("settings_external", "notifications_poll_interval_seconds", int(value))

    @property
    def page_cards_per_page(self) -> int:
        return self._read_db_setting("settings_external", "page_cards_per_page", 20)

    @page_cards_per_page.setter
    def page_cards_per_page(self, value: int) -> None:
        self._write_db_setting("settings_external", "page_cards_per_page", int(value))

    @property
    def crawler_default_max_pages(self) -> int:
        return self._read_db_setting("settings_external", "crawler_default_max_pages", 25)

    @crawler_default_max_pages.setter
    def crawler_default_max_pages(self, value: int) -> None:
        self._write_db_setting("settings_external", "crawler_default_max_pages", int(value))

    @property
    def repo_import_default_depth(self) -> int:
        return self._read_db_setting("settings_external", "repo_import_default_depth", 1)

    @repo_import_default_depth.setter
    def repo_import_default_depth(self, value: int) -> None:
        self._write_db_setting("settings_external", "repo_import_default_depth", int(value))

    @property
    def youtube_download_format(self) -> str:
        return self._read_db_setting(
            "settings_external",
            "youtube_download_format",
            DEFAULT_YOUTUBE_DOWNLOAD_FORMAT,
        )

    @youtube_download_format.setter
    def youtube_download_format(self, value: str) -> None:
        self._write_db_setting(
            "settings_external", "youtube_download_format", str(value).strip()
        )

    def save(self) -> None:
        """Writes current config values back to the ~/.kb/configs/kb-web.json file."""
        try:
            self.configs_dir.mkdir(parents=True, exist_ok=True)
            config_file = self.configs_dir / "kb-web.json"
            data = {
                "database_url": self.database_url,
                "ollama_host": self.ollama_host,
                "ollama_model": self.ollama_model,
                "ollama_embedding_model": self.ollama_embedding_model,
                "trusted_proxies": self.trusted_proxies,
                "admin_password_hash": self.admin_password_hash,
                "admin_password": "[REDACTED]" if not (self.admin_password or "").startswith("scrypt$") else self.admin_password,
                "api_key": "[REDACTED]" if self.api_key else None,
                "wiki_prompt": self.wiki_prompt,
                "youtube_wiki_prompt": self.youtube_wiki_prompt,
                "tags_prompt": self.tags_prompt,
                "rag_system_prompt": self.rag_system_prompt,
                "taxonomy_system_prompt": self.taxonomy_system_prompt,
                "rag_report_prompt": self.rag_report_prompt,
                "maintenance_agent_prompt": self.maintenance_agent_prompt,
                "workspace_agent_prompt": self.workspace_agent_prompt,
                "article_chat_prompt": self.article_chat_prompt,
                "ontology_synthesis_prompt": self.ontology_synthesis_prompt,
                "similarity_threshold": self.similarity_threshold,
                "max_input_length": self.max_input_length,
                "ollama_think": self.ollama_think,
                "ollama_timeout": self.ollama_timeout,
                "rag_search_top_k": self.rag_search_top_k,
                "taxonomy_batch_limit": self.taxonomy_batch_limit,
                "notifications_poll_interval_seconds": self.notifications_poll_interval_seconds,
                "page_cards_per_page": self.page_cards_per_page,
                "crawler_default_max_pages": self.crawler_default_max_pages,
                "repo_import_default_depth": self.repo_import_default_depth,
                "youtube_download_format": self.youtube_download_format,
                "gotify_url": self.gotify_url,
                "gotify_token": self.gotify_token,
                "qdrant_host_url": self.qdrant_host_url,
                "qdrant_api_key": self.qdrant_api_key,
            }
            with open(config_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4)
            print(f"Saved configurations to {config_file}")
        except Exception as e:
            print(f"Error: Failed to save configurations: {e}")

    def get_notifier(self) -> Gotify:
        """Instantiates and returns a Gotify notifier class using the configured token

        and URL details.

        Returns:
            Gotify: A notifier helper from the kb-core package.
        """
        return Gotify(token=self.gotify_token, url=self.gotify_url)
