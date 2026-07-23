"""Context.dev web content extraction provider.

This provider intentionally implements only ``web_extract``. Search routing is
left to the separately configured ``web.search_backend``.

Context.dev's Markdown scrape endpoint costs one credit per successful page.
Requests use its default one-day cache explicitly and carry a Hermes usage tag
so spend can be separated in the Context.dev dashboard.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List

import httpx

from agent.web_search_provider import WebSearchProvider, get_provider_env

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://api.context.dev/v1/"
SCRAPE_PATH = "web/scrape/markdown"
MAX_AGE_MS = 86_400_000
REQUEST_TIMEOUT_MS = 60_000
USAGE_TAG = "hermes-web-extract"


def _base_url() -> str:
    """Return the configured Context.dev API root with one trailing slash."""
    configured = get_provider_env("CONTEXT_DEV_BASE_URL") or DEFAULT_BASE_URL
    return configured.rstrip("/") + "/"


def _new_client(api_key: str) -> httpx.AsyncClient:
    """Build the async client used for one extract batch."""
    return httpx.AsyncClient(
        base_url=_base_url(),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
            "User-Agent": "hermes-agent/context-dev-web-extract",
        },
        follow_redirects=True,
        timeout=httpx.Timeout(70.0, connect=10.0),
    )


def _response_error(response: httpx.Response) -> str:
    """Return a bounded, useful API error without echoing request headers."""
    detail = ""
    try:
        payload = response.json()
        if isinstance(payload, dict):
            code = payload.get("error_code") or payload.get("code")
            message = payload.get("message") or payload.get("error")
            parts = [str(value) for value in (code, message) if value]
            detail = ": ".join(parts)
    except (ValueError, TypeError):
        detail = ""

    suffix = f" ({detail[:300]})" if detail else ""
    return f"Context.dev returned HTTP {response.status_code}{suffix}"


async def _scrape_one(client: httpx.AsyncClient, url: str) -> Dict[str, Any]:
    """Scrape and normalize one URL while containing failures to that URL."""
    params = {
        "url": url,
        "maxAgeMs": str(MAX_AGE_MS),
        "timeoutMS": str(REQUEST_TIMEOUT_MS),
        "shortenBase64Images": "true",
        "pdf[shouldParse]": "true",
        "pdf[ocr]": "false",
        "tags": USAGE_TAG,
    }
    try:
        response = await client.get(SCRAPE_PATH, params=params)
        if response.is_error:
            return {
                "url": url,
                "title": "",
                "content": "",
                "error": _response_error(response),
            }

        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("response body was not a JSON object")

        markdown = payload.get("markdown")
        if not isinstance(markdown, str):
            raise ValueError("response did not contain Markdown")

        metadata = payload.get("metadata")
        if not isinstance(metadata, dict):
            metadata = {}
        title = metadata.get("title")
        if not isinstance(title, str):
            title = ""
        final_url = metadata.get("finalUrl") or payload.get("url") or url
        if not isinstance(final_url, str):
            final_url = url

        normalized_metadata = dict(metadata)
        normalized_metadata.setdefault("sourceURL", url)
        normalized_metadata.setdefault("finalURL", final_url)
        normalized_metadata["provider"] = "context-dev"

        return {
            "url": final_url,
            "title": title,
            "content": markdown,
            "raw_content": markdown,
            "metadata": normalized_metadata,
        }
    except httpx.TimeoutException:
        return {
            "url": url,
            "title": "",
            "content": "",
            "error": "Context.dev extract timed out",
        }
    except httpx.RequestError as exc:
        return {
            "url": url,
            "title": "",
            "content": "",
            "error": f"Context.dev request failed: {type(exc).__name__}",
        }
    except (ValueError, TypeError) as exc:
        return {
            "url": url,
            "title": "",
            "content": "",
            "error": f"Context.dev returned an invalid response: {exc}",
        }


class ContextDevWebExtractProvider(WebSearchProvider):
    """Context.dev extract-only provider."""

    @property
    def name(self) -> str:
        return "context-dev"

    @property
    def display_name(self) -> str:
        return "Context.dev"

    def is_available(self) -> bool:
        return bool(get_provider_env("CONTEXT_DEV_API_KEY"))

    def supports_search(self) -> bool:
        return False

    def supports_extract(self) -> bool:
        return True

    async def extract(self, urls: List[str], **kwargs: Any) -> List[Dict[str, Any]]:
        """Extract URLs concurrently and preserve input order."""
        del kwargs
        api_key = get_provider_env("CONTEXT_DEV_API_KEY")
        if not api_key:
            message = (
                "CONTEXT_DEV_API_KEY environment variable not set. "
                "Get an API key at https://context.dev"
            )
            return [
                {"url": url, "title": "", "content": "", "error": message}
                for url in urls
            ]

        try:
            from tools.interrupt import is_interrupted

            if is_interrupted():
                return [
                    {"url": url, "title": "", "content": "", "error": "Interrupted"}
                    for url in urls
                ]
        except ImportError:
            pass

        logger.info("Context.dev extract: %d URL(s)", len(urls))
        async with _new_client(api_key) as client:
            return list(
                await asyncio.gather(*(_scrape_one(client, url) for url in urls))
            )

    def get_setup_schema(self) -> Dict[str, Any]:
        return {
            "name": "Context.dev",
            "badge": "paid",
            "tag": "Extract-only Markdown scraper with a one-day response cache.",
            "env_vars": [
                {
                    "key": "CONTEXT_DEV_API_KEY",
                    "prompt": "Context.dev API key",
                    "url": "https://context.dev",
                },
            ],
        }
