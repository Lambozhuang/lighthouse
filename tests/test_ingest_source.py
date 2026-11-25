"""Which way a link is read: captions, the plain fetch, or the plain fetch and then the renderer."""

import pytest

from lighthouse.ingest import fetch, render, source, youtube
from lighthouse.ingest.fetch import Page

pytestmark = pytest.mark.asyncio(loop_scope="session")

PLAIN = Page(url="https://blog.example/post", title="Plain", text="from the plain fetch")
RENDERED = Page(url="https://blog.example/post", title="Rendered", text="from the browser")


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Replace the three readers with stand-ins that record which were called."""
    made: list[str] = []

    async def fetch_video(video: str) -> Page:
        made.append(f"video {video}")
        return Page(url="https://www.youtube.com/watch?v=" + video, title=None, text="captions")

    async def render_page(url: str) -> Page:
        made.append("render")
        return RENDERED

    monkeypatch.setattr(youtube, "fetch_video", fetch_video)
    monkeypatch.setattr(render, "render_page", render_page)
    monkeypatch.setattr(render, "enabled", lambda: True)
    return made


def plain_fetch(monkeypatch: pytest.MonkeyPatch, calls: list[str], outcome: Page | Exception) -> None:
    async def fetch_page(url: str) -> Page:
        calls.append("plain")
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(fetch, "fetch_page", fetch_page)


async def test_video_goes_to_captions(monkeypatch: pytest.MonkeyPatch, calls: list[str]) -> None:
    plain_fetch(monkeypatch, calls, PLAIN)
    page = await source.read_url("https://youtu.be/dQw4w9WgXcQ")
    assert page.text == "captions" and calls == ["video dQw4w9WgXcQ"]


async def test_readable_page_never_reaches_the_browser(monkeypatch: pytest.MonkeyPatch, calls: list[str]) -> None:
    plain_fetch(monkeypatch, calls, PLAIN)
    assert await source.read_url("https://blog.example/post") == PLAIN
    assert calls == ["plain"]


@pytest.mark.parametrize(
    "error",
    [fetch.ExtractionError("no text"), fetch.HttpStatusError(403), fetch.HttpStatusError(419)],
    ids=["no text in the HTML", "403", "419"],
)
async def test_browser_is_the_second_attempt(
    monkeypatch: pytest.MonkeyPatch, calls: list[str], error: fetch.FetchError
) -> None:
    plain_fetch(monkeypatch, calls, error)
    assert await source.read_url("https://blog.example/post") == RENDERED
    assert calls == ["plain", "render"]


@pytest.mark.parametrize(
    "error",
    [
        fetch.HttpStatusError(404),
        fetch.HttpStatusError(429),
        fetch.HttpStatusError(503),
        fetch.BlockedUrlError("private"),
        fetch.NetworkError("down"),
        fetch.UnsupportedContentError("image/png"),
        fetch.PageTooLargeError("big"),
    ],
    ids=["404", "429", "503", "blocked address", "network", "not a page", "too large"],
)
async def test_failures_a_browser_would_not_fix(
    monkeypatch: pytest.MonkeyPatch, calls: list[str], error: fetch.FetchError
) -> None:
    plain_fetch(monkeypatch, calls, error)
    with pytest.raises(type(error)):
        await source.read_url("https://blog.example/post")
    assert calls == ["plain"]


async def test_without_a_renderer_the_plain_error_stands(monkeypatch: pytest.MonkeyPatch, calls: list[str]) -> None:
    monkeypatch.setattr(render, "enabled", lambda: False)
    plain_fetch(monkeypatch, calls, fetch.ExtractionError("It may need JavaScript; paste the text instead"))
    with pytest.raises(fetch.ExtractionError, match="paste the text"):
        await source.read_url("https://blog.example/post")
    assert calls == ["plain"]
