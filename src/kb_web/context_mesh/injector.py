"""Subconscious Context Auto-Injector.

Injects intent-grounded context statements into agent system prompts
automatically in the background without explicit search queries from the agent.
"""

from __future__ import annotations

import logging
from typing import Optional, Tuple

from .models import AssembledContext
from .retriever import BubbleDownRetriever

logger = logging.getLogger(__name__)


class SubconsciousContextInjector:
    """Provides subconscious context injection into agent prompts.

    Emulates human memory recall by auto-retrieving relevant principles,
    conventions, and concrete facts into the prompt's background instructions.
    """

    def __init__(self, retriever: Optional[BubbleDownRetriever] = None) -> None:
        self.retriever = retriever or BubbleDownRetriever()

    def inject_subconscious_context(
        self,
        prompt: str,
        user_query: str,
        top_k_per_layer: int = 2,
    ) -> Tuple[str, AssembledContext]:
        """Retrieve relevant context for user_query and inject it into prompt instructions."""
        assembled = self.retriever.retrieve(query=user_query, top_k_per_layer=top_k_per_layer)

        if not assembled.statements:
            return prompt, assembled

        context_xml = (
            "\n<subconscious_context>\n"
            f"{assembled.formatted_context_block}\n"
            "</subconscious_context>\n"
        )

        injected_prompt = f"{prompt.rstrip()}\n{context_xml}"
        return injected_prompt, assembled


_global_injector: Optional[SubconsciousContextInjector] = None


def get_subconscious_injector() -> SubconsciousContextInjector:
    """Return singleton instance of SubconsciousContextInjector."""
    global _global_injector
    if _global_injector is None:
        _global_injector = SubconsciousContextInjector()
    return _global_injector


def auto_inject_subconscious_context(prompt: str, user_query: str) -> str:
    """Convenience helper to auto-inject subconscious context into prompt."""
    injector = get_subconscious_injector()
    injected, _ = injector.inject_subconscious_context(prompt, user_query)
    return injected
