"""
Configuration for the kb-web application.
"""

import json
import os
from typing import Optional

from kb_core.config import Config as BaseConfig
from kb_core.notifier import Gotify

DEFAULT_WIKI_PROMPT = (
    "You are an expert knowledge-base engineer. Extract the core informational content "
    "from the provided web page markdown and rewrite it as a clean, highly structured, "
    "and objective wiki entry. The entry MUST start with a markdown header level 1 (#) representing "
    "a descriptive and clear title for the page (e.g. '# Quickstart Guide for Python'). "
    "Strip out all ads, clickbait, sidebars, navigation links, cookie banners, "
    "and user comments. Keep only the valuable data, analysis, code blocks, or technical tutorials. "
    "Output ONLY the final markdown text. Do not reply with conversational filler headers."
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




class Config(BaseConfig):
    """Configuration class for the kb-web application.

    Inherits from the base kb-core Config class and adds properties for
    managing the Ollama host/model, administrative UI password, Gotify
    notification parameters, wiki system prompts, and browser extension API keys.
    Supports parsing from a config file (kb-web.json) or falling back to
    environment variables.
    """

    def __init__(self) -> None:
        """Initializes configuration properties with default values and overlays

        from the config file (~/.kb/configs/kb-web.json) or environment variables.
        """
        super().__init__()
        # 1. Apply defaults or environment variables first
        self._ollama_host: str = os.getenv("KB_OLLAMA_HOST", "http://localhost:11434")
        self._ollama_model: str = os.getenv("KB_OLLAMA_MODEL", "gemma4:latest")
        self._ollama_embedding_model: str = os.getenv(
            "KB_OLLAMA_EMBEDDING_MODEL", "nomic-embed-text"
        )
        self._admin_password: str = os.getenv("KB_PASSWORD", "admin123")
        self._api_key: Optional[str] = os.getenv("KB_API_KEY", "kb-secret-key")
        self._wiki_prompt: str = os.getenv("KB_WIKI_PROMPT", DEFAULT_WIKI_PROMPT)
        self._youtube_wiki_prompt: str = os.getenv("KB_YOUTUBE_WIKI_PROMPT", DEFAULT_YOUTUBE_WIKI_PROMPT)
        self._similarity_threshold: float = float(os.getenv("KB_SIMILARITY_THRESHOLD", "0.8"))
        self._max_input_length: int = int(os.getenv("KB_MAX_INPUT_LENGTH", "20000"))
        self._ollama_think: bool = os.getenv("KB_OLLAMA_THINK", "false").lower() in ("true", "1")
        self._gotify_url: Optional[str] = os.getenv("GOTIFY_URL")
        self._gotify_token: Optional[str] = os.getenv("GOTIFY_TOKEN")
        self._qdrant_host_url: Optional[str] = os.getenv("QDRANT_HOST_URL")
        self._qdrant_api_key: Optional[str] = os.getenv("QDRANT_API_KEY")

        # 2. Overlay values from JSON configuration file if it exists
        try:
            config_file = self.configs_dir / "kb-web.json"
            if config_file.exists():
                with open(config_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if "ollama_host" in data:
                        self._ollama_host = data["ollama_host"]
                    if "ollama_model" in data:
                        self._ollama_model = data["ollama_model"]
                    if "ollama_embedding_model" in data:
                        self._ollama_embedding_model = data["ollama_embedding_model"]
                    if "admin_password" in data:
                        self._admin_password = data["admin_password"]
                    if "api_key" in data:
                        self._api_key = data["api_key"]
                    if "wiki_prompt" in data:
                        self._wiki_prompt = data["wiki_prompt"]
                    if "youtube_wiki_prompt" in data:
                        self._youtube_wiki_prompt = data["youtube_wiki_prompt"]
                    if "similarity_threshold" in data:
                        self._similarity_threshold = float(data["similarity_threshold"])
                    if "max_input_length" in data:
                        self._max_input_length = int(data["max_input_length"])
                    if "ollama_think" in data:
                        self._ollama_think = bool(data["ollama_think"])
                    if "gotify_url" in data:
                        self._gotify_url = data["gotify_url"]
                    if "gotify_token" in data:
                        self._gotify_token = data["gotify_token"]
                    if "qdrant_host_url" in data:
                        self._qdrant_host_url = data["qdrant_host_url"]
                    if "qdrant_api_key" in data:
                        self._qdrant_api_key = data["qdrant_api_key"]
        except Exception as e:
            # Suppress logs or print warning during startup if reading fails
            print(f"Warning: Failed to load config file 'kb-web.json': {e}")

    def _read_db_setting(self, table: str, key: str, default):
        try:
            db = self.get_db()
            if table in db.table_names():
                row = db[table].get(key)
                if row and row.get("value") is not None:
                    val = row["value"]
                    if isinstance(default, bool):
                        return val.lower() in ("true", "1")
                    if isinstance(default, int):
                        return int(val)
                    if isinstance(default, float):
                        return float(val)
                    return val
        except Exception:
            pass
        return default

    def _write_db_setting(self, table: str, key: str, value) -> None:
        try:
            db = self.get_db()
            if table in db.table_names():
                val_str = str(value)
                db[table].upsert({"key": key, "value": val_str}, pk="key")
                db.conn.commit()
        except Exception:
            pass

    @property
    def ollama_host(self) -> str:
        return self._read_db_setting("settings_ollama", "ollama_host", self._ollama_host)
        
    @ollama_host.setter
    def ollama_host(self, value: str) -> None:
        self._ollama_host = value
        self._write_db_setting("settings_ollama", "ollama_host", value)

    @property
    def ollama_model(self) -> str:
        return self._read_db_setting("settings_ollama", "ollama_model", self._ollama_model)
        
    @ollama_model.setter
    def ollama_model(self, value: str) -> None:
        self._ollama_model = value
        self._write_db_setting("settings_ollama", "ollama_model", value)

    @property
    def ollama_embedding_model(self) -> str:
        return self._read_db_setting("settings_ollama", "ollama_embedding_model", self._ollama_embedding_model)
        
    @ollama_embedding_model.setter
    def ollama_embedding_model(self, value: str) -> None:
        self._ollama_embedding_model = value
        self._write_db_setting("settings_ollama", "ollama_embedding_model", value)

    @property
    def max_input_length(self) -> int:
        return self._read_db_setting("settings_ollama", "max_input_length", self._max_input_length)
        
    @max_input_length.setter
    def max_input_length(self, value: int) -> None:
        self._max_input_length = value
        self._write_db_setting("settings_ollama", "max_input_length", value)

    @property
    def ollama_think(self) -> bool:
        return self._read_db_setting("settings_ollama", "ollama_think", self._ollama_think)
        
    @ollama_think.setter
    def ollama_think(self, value: bool) -> None:
        self._ollama_think = value
        self._write_db_setting("settings_ollama", "ollama_think", "1" if value else "0")

    @property
    def admin_password(self) -> str:
        return self._read_db_setting("settings_external", "admin_password", self._admin_password)
        
    @admin_password.setter
    def admin_password(self, value: str) -> None:
        self._admin_password = value
        self._write_db_setting("settings_external", "admin_password", value)

    @property
    def api_key(self) -> Optional[str]:
        val = self._read_db_setting("settings_external", "api_key", self._api_key)
        return val if val else None
        
    @api_key.setter
    def api_key(self, value: Optional[str]) -> None:
        self._api_key = value
        self._write_db_setting("settings_external", "api_key", value or "")

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
        val = self._read_db_setting("settings_external", "gotify_token", self._gotify_token)
        return val if val else None
        
    @gotify_token.setter
    def gotify_token(self, value: Optional[str]) -> None:
        self._gotify_token = value
        self._write_db_setting("settings_external", "gotify_token", value or "")

    @property
    def qdrant_host_url(self) -> Optional[str]:
        val = self._read_db_setting("settings_external", "qdrant_host_url", self._qdrant_host_url)
        return val if val else None
        
    @qdrant_host_url.setter
    def qdrant_host_url(self, value: Optional[str]) -> None:
        self._qdrant_host_url = value
        self._write_db_setting("settings_external", "qdrant_host_url", value or "")

    @property
    def qdrant_api_key(self) -> Optional[str]:
        val = self._read_db_setting("settings_external", "qdrant_api_key", self._qdrant_api_key)
        return val if val else None
        
    @qdrant_api_key.setter
    def qdrant_api_key(self, value: Optional[str]) -> None:
        self._qdrant_api_key = value
        self._write_db_setting("settings_external", "qdrant_api_key", value or "")

    @property
    def similarity_threshold(self) -> float:
        return self._read_db_setting("settings_external", "similarity_threshold", self._similarity_threshold)
        
    @similarity_threshold.setter
    def similarity_threshold(self, value: float) -> None:
        self._similarity_threshold = value
        self._write_db_setting("settings_external", "similarity_threshold", value)

    @property
    def wiki_prompt(self) -> str:
        try:
            db = self.get_db()
            if "agent_prompts" in db.table_names():
                rows = list(db["agent_prompts"].rows_where("prompt_type = 'wiki_prompt' AND is_head = 1"))
                if rows:
                    return rows[0]["prompt_text"]
        except Exception:
            pass
        return self._wiki_prompt

    @wiki_prompt.setter
    def wiki_prompt(self, value: str) -> None:
        self._wiki_prompt = value
        try:
            db = self.get_db()
            if "agent_prompts" in db.table_names():
                current_head = None
                rows = list(db["agent_prompts"].rows_where("prompt_type = 'wiki_prompt' AND is_head = 1"))
                if rows:
                    current_head = rows[0]["prompt_text"]
                
                if current_head != value:
                    from datetime import datetime
                    max_version = 0
                    all_versions = list(db.execute_returning_dicts(
                        "SELECT MAX(version) as mv FROM agent_prompts WHERE prompt_type = 'wiki_prompt'"
                    ))
                    if all_versions and all_versions[0]["mv"] is not None:
                        max_version = all_versions[0]["mv"]
                        
                    db.execute("UPDATE agent_prompts SET is_head = 0 WHERE prompt_type = 'wiki_prompt'")
                    db["agent_prompts"].insert({
                        "prompt_type": "wiki_prompt",
                        "prompt_text": value,
                        "is_head": 1,
                        "version": max_version + 1,
                        "created_at": datetime.now().isoformat()
                    })
                    db.conn.commit()
        except Exception as e:
            print(f"Error setting wiki_prompt: {e}")

    @property
    def youtube_wiki_prompt(self) -> str:
        try:
            db = self.get_db()
            if "agent_prompts" in db.table_names():
                rows = list(db["agent_prompts"].rows_where("prompt_type = 'youtube_wiki_prompt' AND is_head = 1"))
                if rows:
                    return rows[0]["prompt_text"]
        except Exception:
            pass
        return self._youtube_wiki_prompt

    @youtube_wiki_prompt.setter
    def youtube_wiki_prompt(self, value: str) -> None:
        self._youtube_wiki_prompt = value
        try:
            db = self.get_db()
            if "agent_prompts" in db.table_names():
                current_head = None
                rows = list(db["agent_prompts"].rows_where("prompt_type = 'youtube_wiki_prompt' AND is_head = 1"))
                if rows:
                    current_head = rows[0]["prompt_text"]
                
                if current_head != value:
                    from datetime import datetime
                    max_version = 0
                    all_versions = list(db.execute_returning_dicts(
                        "SELECT MAX(version) as mv FROM agent_prompts WHERE prompt_type = 'youtube_wiki_prompt'"
                    ))
                    if all_versions and all_versions[0]["mv"] is not None:
                        max_version = all_versions[0]["mv"]
                        
                    db.execute("UPDATE agent_prompts SET is_head = 0 WHERE prompt_type = 'youtube_wiki_prompt'")
                    db["agent_prompts"].insert({
                        "prompt_type": "youtube_wiki_prompt",
                        "prompt_text": value,
                        "is_head": 1,
                        "version": max_version + 1,
                        "created_at": datetime.now().isoformat()
                    })
                    db.conn.commit()
        except Exception as e:
            print(f"Error setting youtube_wiki_prompt: {e}")

    def save(self) -> None:
        """Writes current config values back to the ~/.kb/configs/kb-web.json file."""
        try:
            self.configs_dir.mkdir(parents=True, exist_ok=True)
            config_file = self.configs_dir / "kb-web.json"
            data = {
                "ollama_host": self.ollama_host,
                "ollama_model": self.ollama_model,
                "ollama_embedding_model": self.ollama_embedding_model,
                "admin_password": self.admin_password,
                "api_key": self.api_key,
                "wiki_prompt": self.wiki_prompt,
                "youtube_wiki_prompt": self.youtube_wiki_prompt,
                "similarity_threshold": self.similarity_threshold,
                "max_input_length": self.max_input_length,
                "ollama_think": self.ollama_think,
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
