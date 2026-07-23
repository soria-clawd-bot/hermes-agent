"""Focused tests for the Context.dev native web-extract provider."""

from __future__ import annotations

import json

import httpx
import pytest

from plugins.web.context_dev import provider as context_provider
from plugins.web.context_dev.provider import ContextDevWebExtractProvider


@pytest.fixture(autouse=True)
def _clear_context_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CONTEXT_DEV_API_KEY", raising=False)
    monkeypatch.delenv("CONTEXT_DEV_BASE_URL", raising=False)


def _mock_client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url="https://api.context.test/v1/",
        headers={"Authorization": "Bearer secret"},
        transport=httpx.MockTransport(handler),
    )


@pytest.mark.asyncio
async def test_extract_calls_markdown_endpoint_and_normalizes_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "success": True,
                "url": "https://example.com",
                "markdown": "# Example\n\nUseful content.",
                "contentLength": 27,
                "metadata": {
                    "title": "Example",
                    "sourceUrl": "https://example.com",
                    "finalUrl": "https://www.example.com/",
                },
                "key_metadata": {"credits_consumed": 1},
            },
        )

    monkeypatch.setenv("CONTEXT_DEV_API_KEY", "secret")
    monkeypatch.setattr(
        context_provider, "_new_client", lambda api_key: _mock_client(handler)
    )

    results = await ContextDevWebExtractProvider().extract(["https://example.com"])

    assert len(seen) == 1
    request = seen[0]
    assert request.url.path == "/v1/web/scrape/markdown"
    assert request.headers["Authorization"] == "Bearer secret"
    assert request.url.params["url"] == "https://example.com"
    assert request.url.params["maxAgeMs"] == "86400000"
    assert request.url.params["timeoutMS"] == "60000"
    assert request.url.params["pdf[shouldParse]"] == "true"
    assert request.url.params["tags"] == "hermes-web-extract"
    assert results == [
        {
            "url": "https://www.example.com/",
            "title": "Example",
            "content": "# Example\n\nUseful content.",
            "raw_content": "# Example\n\nUseful content.",
            "metadata": {
                "title": "Example",
                "sourceUrl": "https://example.com",
                "finalUrl": "https://www.example.com/",
                "sourceURL": "https://example.com",
                "finalURL": "https://www.example.com/",
                "provider": "context-dev",
            },
        }
    ]


@pytest.mark.asyncio
async def test_extract_preserves_order_and_contains_per_url_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_scrape(_client, url: str):
        if url.endswith("/bad"):
            return {
                "url": url,
                "title": "",
                "content": "",
                "error": "Context.dev returned HTTP 404",
            }
        return {
            "url": url,
            "title": "Good",
            "content": "ok",
            "raw_content": "ok",
            "metadata": {"provider": "context-dev"},
        }

    monkeypatch.setenv("CONTEXT_DEV_API_KEY", "secret")
    monkeypatch.setattr(
        context_provider,
        "_new_client",
        lambda api_key: _mock_client(lambda request: httpx.Response(500)),
    )
    monkeypatch.setattr(context_provider, "_scrape_one", fake_scrape)

    urls = ["https://example.com/good", "https://example.com/bad"]
    results = await ContextDevWebExtractProvider().extract(urls)

    assert [result["url"] for result in results] == urls
    assert results[0]["content"] == "ok"
    assert results[1]["error"] == "Context.dev returned HTTP 404"


@pytest.mark.asyncio
async def test_extract_returns_precise_missing_key_error() -> None:
    results = await ContextDevWebExtractProvider().extract(["https://example.com"])

    assert "CONTEXT_DEV_API_KEY environment variable not set" in results[0]["error"]
    assert results[0]["url"] == "https://example.com"


@pytest.mark.asyncio
async def test_extract_bounds_api_error_detail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429,
            json={"error_code": "rate_limited", "message": "retry later"},
        )

    monkeypatch.setenv("CONTEXT_DEV_API_KEY", "secret")
    monkeypatch.setattr(
        context_provider, "_new_client", lambda api_key: _mock_client(handler)
    )

    results = await ContextDevWebExtractProvider().extract(["https://example.com"])

    assert results[0]["error"] == (
        "Context.dev returned HTTP 429 (rate_limited: retry later)"
    )


@pytest.mark.asyncio
async def test_native_web_extract_routes_to_context_dev(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import tools.web_tools as web_tools

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "success": True,
                "url": "https://example.com",
                "markdown": "# Routed through Context.dev",
                "contentLength": 28,
                "metadata": {
                    "title": "Native route",
                    "sourceUrl": "https://example.com",
                    "finalUrl": "https://example.com",
                },
            },
        )

    async def safe_url(_url: str) -> bool:
        return True

    monkeypatch.setenv("CONTEXT_DEV_API_KEY", "secret")
    monkeypatch.setattr(
        context_provider, "_new_client", lambda api_key: _mock_client(handler)
    )
    monkeypatch.setattr(
        web_tools,
        "_load_web_config",
        lambda: {
            "backend": "firecrawl",
            "search_backend": "parallel",
            "extract_backend": "context-dev",
        },
    )
    monkeypatch.setattr(web_tools, "async_is_safe_url", safe_url)

    result = json.loads(
        await web_tools.web_extract_tool(
            ["https://example.com"],
            char_limit=15_000,
        )
    )

    assert result["results"] == [
        {
            "url": "https://example.com",
            "title": "Native route",
            "content": "# Routed through Context.dev",
            "error": None,
        }
    ]
