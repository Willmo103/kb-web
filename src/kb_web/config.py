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
        self.ollama_host: str = os.getenv("KB_OLLAMA_HOST", "http://localhost:11434")
        self.ollama_model: str = os.getenv("KB_OLLAMA_MODEL", "gemma4:latest")
        self.ollama_embedding_model: str = os.getenv(
            "KB_OLLAMA_EMBEDDING_MODEL", "nomic-embed-text"
        )
        self.admin_password: str = os.getenv("KB_PASSWORD", "admin123")
        self.api_key: Optional[str] = os.getenv("KB_API_KEY", "kb-secret-key")
        self.wiki_prompt: str = os.getenv("KB_WIKI_PROMPT", DEFAULT_WIKI_PROMPT)
        self.youtube_wiki_prompt: str = os.getenv("KB_YOUTUBE_WIKI_PROMPT", DEFAULT_YOUTUBE_WIKI_PROMPT)
        self.similarity_threshold: float = float(os.getenv("KB_SIMILARITY_THRESHOLD", "0.8"))
        self.gotify_url: Optional[str] = os.getenv("GOTIFY_URL")
        self.gotify_token: Optional[str] = os.getenv("GOTIFY_TOKEN")

        # 2. Overlay values from JSON configuration file if it exists
        try:
            config_file = self.configs_dir / "kb-web.json"
            if config_file.exists():
                with open(config_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if "ollama_host" in data:
                        self.ollama_host = data["ollama_host"]
                    if "ollama_model" in data:
                        self.ollama_model = data["ollama_model"]
                    if "ollama_embedding_model" in data:
                        self.ollama_embedding_model = data["ollama_embedding_model"]
                    if "admin_password" in data:
                        self.admin_password = data["admin_password"]
                    if "api_key" in data:
                        self.api_key = data["api_key"]
                    if "wiki_prompt" in data:
                        self.wiki_prompt = data["wiki_prompt"]
                    if "youtube_wiki_prompt" in data:
                        self.youtube_wiki_prompt = data["youtube_wiki_prompt"]
                    if "similarity_threshold" in data:
                        self.similarity_threshold = float(data["similarity_threshold"])
                    if "gotify_url" in data:
                        self.gotify_url = data["gotify_url"]
                    if "gotify_token" in data:
                        self.gotify_token = data["gotify_token"]
        except Exception as e:
            # Suppress logs or print warning during startup if reading fails
            print(f"Warning: Failed to load config file 'kb-web.json': {e}")

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
                "gotify_url": self.gotify_url,
                "gotify_token": self.gotify_token,
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
