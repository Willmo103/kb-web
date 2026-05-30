from pathlib import Path
import os
import json
from typing import Optional

from kb_core.config import Config as BaseConfig
from kb_core.notifier import Gotify


class Config(BaseConfig):
    """Configuration class for the kb-web application.

    Inherits from the base kb-core Config class and adds properties for
    managing the Ollama host, administrative UI password, and Gotify
    notification parameters. Supports parsing from a config file
    (kb-web.json) or falling back to environment variables.
    """

    def __init__(self) -> None:
        """Initializes configuration properties with default values and overlays

        from the config file (~/.kb/configs/kb-web.json) or environment variables.
        """
        super().__init__()
        # 1. Apply defaults or environment variables first
        self.ollama_host: str = os.getenv("KB_OLLAMA_HOST", "http://localhost:11434")
        self.admin_password: str = os.getenv("KB_PASSWORD", "admin123")
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
                    if "admin_password" in data:
                        self.admin_password = data["admin_password"]
                    if "gotify_url" in data:
                        self.gotify_url = data["gotify_url"]
                    if "gotify_token" in data:
                        self.gotify_token = data["gotify_token"]
        except Exception as e:
            # Suppress logs or print warning during startup if reading fails
            print(f"Warning: Failed to load config file 'kb-web.json': {e}")

    def get_notifier(self) -> Gotify:
        """Instantiates and returns a Gotify notifier class using the configured token

        and URL details.

        Returns:
            Gotify: A notifier helper from the kb-core package.
        """
        return Gotify(token=self.gotify_token, url=self.gotify_url)
