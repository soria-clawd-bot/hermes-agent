"""Context.dev web content extraction plugin."""

from __future__ import annotations

from plugins.web.context_dev.provider import ContextDevWebExtractProvider


def register(ctx) -> None:
    """Register the Context.dev extract-only provider."""
    ctx.register_web_search_provider(ContextDevWebExtractProvider())
