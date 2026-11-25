"""The renderer client. The Crawl4AI server is a mock transport that answers like the real one."""

import json
from collections.abc import Iterator
from typing import Any

import httpx
import pytest

from lighthouse.config import get_settings
from lighthouse.ingest import fetch, render

pytestmark = [pytest.mark.asyncio(loop_scope="session"), pytest.mark.usefixtures("dns", "renderer")]

PUBLIC_IP = "93.184.216.34"
TEXT = "# Quick start\n\n" + "This page is drawn by JavaScript after it loads. " * 10


@pytest.fixture
def renderer(monkeypatch: pytest.MonkeyPatch, dns: dict[str, list[str]]) -> Iterator[None]:
    monkeypatch.setenv("RENDER_URL", "http://crawl4ai:11235")
    monkeypatch.setenv("RENDER_TOKEN", "test-token")
    get_settings.cache_clear()
    dns["app.example"] = [PUBLIC_IP]
    yield
    monkeypatch.undo()
    get_settings.cache_clear()


def answer(**changes: Any) -> dict[str, Any]:
    result = {
        "url": "https://app.example/docs",
        "success": True,
        "status_code": 200,
        "error_message": "",
        "redirected_url": "https://app.example/docs",
        "metadata": {"title": " Quick start – App "},
        "markdown": {"raw_markdown": "Menu Home Docs\n" + TEXT, "fit_markdown": TEXT},
    }
    return {"success": True, "results": [result | changes]}


def server(body: dict[str, Any], seen: list[httpx.Request] | None = None) -> httpx.MockTransport:
    def handle(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        return httpx.Response(200, json=body)

    return httpx.MockTransport(handle)


async def test_rendered_page() -> None:
    seen: list[httpx.Request] = []
    page = await render.render_page("https://app.example/docs", transport=server(answer(), seen))

    assert page == fetch.Page(url="https://app.example/docs", title="Quick start – App", text=TEXT.strip())
    (request,) = seen
    assert str(request.url) == "http://crawl4ai:11235/crawl"
    assert request.headers["authorization"] == "Bearer test-token"
    sent = json.loads(request.content)
    assert sent["urls"] == ["https://app.example/docs"]
    assert sent["crawler_config"]["params"]["cache_mode"] == "bypass"


async def test_unfiltered_markdown_is_used_when_the_filter_leaves_nothing() -> None:
    body = answer(markdown={"raw_markdown": TEXT, "fit_markdown": ""})
    page = await render.render_page("https://app.example/docs", transport=server(body))
    assert page.text == TEXT.strip()


async def test_private_address_is_never_sent_to_the_renderer() -> None:
    seen: list[httpx.Request] = []
    with pytest.raises(fetch.BlockedUrlError):
        await render.render_page("http://192.168.1.1/admin", transport=server(answer(), seen))
    assert seen == []


async def test_page_that_ends_on_a_private_address_is_dropped(dns: dict[str, list[str]]) -> None:
    dns["intranet.example"] = ["10.0.0.5"]
    body = answer(redirected_url="http://intranet.example/secret")
    with pytest.raises(fetch.BlockedUrlError):
        await render.render_page("https://app.example/docs", transport=server(body))


async def test_wall_instead_of_the_page() -> None:
    wall = "# Prove your humanity\n\n" + "Complete the challenge below and let us know you are a real person. " * 3
    assert len(wall) > fetch.MIN_TEXT_CHARS  # long enough to pass as an article in the plain fetch
    body = answer(markdown={"raw_markdown": wall, "fit_markdown": ""})
    with pytest.raises(fetch.ExtractionError, match="paste the text instead") as raised:
        await render.render_page("https://app.example/docs", transport=server(body))
    assert not raised.value.retryable


async def test_page_that_does_not_load() -> None:
    body = answer(success=False, error_message="Page.goto: Timeout 30000ms exceeded.\nCall log: ...")
    with pytest.raises(render.RenderError, match="Timeout 30000ms exceeded") as raised:
        await render.render_page("https://app.example/docs", transport=server(body))
    assert "Call log" not in str(raised.value)


async def test_error_status_in_the_browser() -> None:
    with pytest.raises(render.RenderError, match="403"):
        await render.render_page("https://app.example/docs", transport=server(answer(status_code=403)))


async def test_renderer_down_is_retryable() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    with pytest.raises(fetch.NetworkError, match="renderer") as raised:
        await render.render_page("https://app.example/docs", transport=httpx.MockTransport(refuse))
    assert raised.value.retryable


async def test_renderer_refusing_the_request() -> None:
    refuse = httpx.MockTransport(lambda request: httpx.Response(401, json={"detail": "Authentication required"}))
    with pytest.raises(render.RenderError, match="401") as raised:
        await render.render_page("https://app.example/docs", transport=refuse)
    assert not raised.value.retryable


async def test_unreadable_answer() -> None:
    with pytest.raises(render.RenderError, match="could not be read"):
        await render.render_page("https://app.example/docs", transport=server({"results": []}))
