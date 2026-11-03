"""Personal Value-Knowledge (VK) Context Mesh Layer.

Manages curated, nested key-value pairs representing the user's personal interests,
values, operational principles, and subjective context as a frozen context layer
injected into agent prompts and taxonomic steering.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional

from ..base import config as default_config

logger = logging.getLogger("kb_web.context_mesh.personal_vk")

VK_CONFIG_FILE = Path.home() / ".kb" / "personal_vk_context.json"
SETTING_EXTERNAL_KEY = "personal_vk_context_json"


def get_default_personal_vk() -> Dict[str, Any]:
    """Baseline default nested personal VK context."""
    return {
        "interests": {
            "technology": [
                "FastAPI and Python asynchronous backends",
                "Local Ollama models and agentic tool workflows",
                "PostgreSQL and vector retrieval architectures",
                "Deterministic structured classification",
            ],
            "outdoors_and_leisure": [
                "Ultralight backpacking and minimalist gear",
                "River conservation, wild trout, and aquatic ecosystems",
                "Open-source hardware and local automation",
            ],
        },
        "values": {
            "epistemic": [
                "Ground all inferences strictly in verified retrieved text",
                "Reject speculative hallucination and unsupported claims",
                "Preserve historical sources and immutable content versions",
            ],
            "operational": [
                "Strict privacy and 100% local data residency",
                "User steering takes complete precedence over autonomous model defaults",
                "Clean declarative schemas and explicit configuration transparency",
            ],
        },
        "curation_rules": {
            "prefer_official_documentation": True,
            "filter_clickbait_and_spam": True,
            "auto_freeze_reference_materials": True,
        },
    }


class PersonalVKManager:
    """Manages reading, persisting, and formatting the nested personal VK context layer."""

    def __init__(self, config_obj: Any = None) -> None:
        self.config = config_obj or default_config

    def get_context(self) -> Dict[str, Any]:
        """Load personal VK context dictionary from disk, DB, or baseline defaults."""
        # 1. Disk
        if VK_CONFIG_FILE.exists():
            try:
                with open(VK_CONFIG_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        return data
            except Exception as e:
                logger.warning(f"Failed loading personal VK context from {VK_CONFIG_FILE}: {e}")

        # 2. DB
        try:
            db_val = self.config._read_db_setting("settings_external", SETTING_EXTERNAL_KEY, None)
            if db_val:
                data = json.loads(db_val)
                if isinstance(data, dict):
                    return data
        except Exception as e:
            logger.warning(f"Failed loading personal VK context from DB: {e}")

        # 3. Default
        default_data = get_default_personal_vk()
        self.save_context(default_data)
        return default_data

    def save_context(self, context_dict: Dict[str, Any]) -> Dict[str, Any]:
        """Save nested personal VK context to disk and DB setting."""
        if not isinstance(context_dict, dict):
            raise ValueError("Personal VK context must be a dictionary.")

        json_str = json.dumps(context_dict, indent=2)

        # 1. Disk
        try:
            VK_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(VK_CONFIG_FILE, "w", encoding="utf-8") as f:
                f.write(json_str)
        except Exception as e:
            logger.error(f"Failed writing personal VK context to {VK_CONFIG_FILE}: {e}")

        # 2. DB
        try:
            self.config._write_db_setting("settings_external", SETTING_EXTERNAL_KEY, json_str)
        except Exception as e:
            logger.error(f"Failed writing personal VK context to DB: {e}")

        return context_dict

    def format_for_prompt(self) -> str:
        """Format nested personal VK pairs as a clean XML block for agent prompts."""
        context = self.get_context()
        if not context:
            return ""

        formatted_json = json.dumps(context, indent=2)
        return (
            "<personal_values_context>\n"
            "<!-- USER STEERED PERSONAL VALUES, INTERESTS, AND CURATION DIRECTIVES -->\n"
            f"{formatted_json}\n"
            "</personal_values_context>"
        )


_global_vk_manager: Optional[PersonalVKManager] = None


def get_personal_vk_manager() -> PersonalVKManager:
    """Singleton getter for PersonalVKManager."""
    global _global_vk_manager
    if _global_vk_manager is None:
        _global_vk_manager = PersonalVKManager()
    return _global_vk_manager

