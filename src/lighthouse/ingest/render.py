"""Read a page with a real browser, for pages the plain fetch cannot read.

Many sites send an almost empty HTML file and build the page with JavaScript; some turn away
anything that is not a browser. For those the worker asks a Crawl4AI server (a separate
container, see docker-compose.yml) to open the page in headless Chromium, wait for it to load
and return the content as Markdown.

It is slower and heavier than `fetch.py` (a browser instead of one HTTP request), so it is only
the second attempt; `source.py` decides when.

What it still cannot read: pages behind a login or a paywall, and sites that test for automation
(the browser is not disguised). Those need the text pasted.

Internal addresses: the URL goes through the same check as in `fetch.py` before it is sent, and
the address the browser ended up on is checked afterwards. In between the browser follows
redirects on its own; Crawl4AI refuses private addresses itself, and in compose the container
sits on a network of its own from which it cannot reach the database or the other services.
"""

import httpx

from lighthouse.config import get_settings
from lighthouse.ingest.fetch import (
    BlockedUrlError,
    ExtractionError,
    FetchError,
    NetworkError,
    Page,
    public_address,
)

PAGE_TIMEOUT_MS = 30_000  # the browser's own limit for loading the page
REQUEST_TIMEOUT_SECONDS = 60  # ours, for the whole call: queueing, loading, converting
# Higher than the plain fetch asks for (200). A page only gets here when its HTML had no text,
# and what a browser then shows in a few lines is nearly always a wall: "sign in to continue",
# "prove you are human", a cookie notice. Measured: such pages run to 150 to 250 characters.
MIN_TEXT_CHARS = 500

# Crawl4AI's request format: objects are written as {"type": class name, "params": {...}} and
# plain dictionaries as {"type": "dict", "value": {...}}.
CRAWLER_CONFIG = {
    "type": "CrawlerRunConfig",
    "params": {
        "cache_mode": "bypass",  # always the page as it is now
        "page_timeout": PAGE_TIMEOUT_MS,
        "markdown_generator": {
            "type": "DefaultMarkdownGenerator",
            "params": {
                # Drops blocks that look like navigation or boilerplate (low text density,
                # mostly links). The result is `fit_markdown`; without a filter it stays empty.
                "content_filter": {"type": "PruningContentFilter", "params": {}},
                # Link targets and images are noise for a note and for the embedding.
                "options": {"type": "dict", "value": {"ignore_links": True, "ignore_images": True}},
            },
        },
    },
}
BROWSER_CONFIG = {"type": "BrowserConfig", "params": {"headless": True}}


class RenderError(FetchError):
    """The renderer could not load the page."""


def enabled() -> bool:
    return bool(get_settings().render_url)


async def render_page(url: str, *, transport: httpx.AsyncBaseTransport | None = None) -> Page:
    """Open `url` in the renderer's browser and return its content. `transport` is for tests."""
    settings = get_settings()
    await public_address(httpx.URL(url))
    try:
        async with httpx.AsyncClient(
            base_url=settings.render_url,
            transport=transport,
            timeout=REQUEST_TIMEOUT_SECONDS,
            trust_env=False,
            headers={"Authorization": f"Bearer {settings.render_token}"},
        ) as client:
            response = await client.post(
                "/crawl", json={"urls": [url], "browser_config": BROWSER_CONFIG, "crawler_config": CRAWLER_CONFIG}
            )
    except httpx.HTTPError as exc:
        # The container is down, restarting or overloaded: worth another attempt later.
        raise NetworkError(f"The page renderer did not answer ({type(exc).__name__})") from exc
    if response.status_code != 200:
        # 400 is the renderer refusing the request (it has its own private-address check); 401/403
        # mean our token is wrong. Neither gets better by retrying.
        raise RenderError(f"The page renderer refused the request (HTTP {response.status_code})")

    try:
        result = response.json()["results"][0]
        success = bool(result["success"])
        markdown = result.get("markdown") or {}
        text = (markdown.get("fit_markdown") or markdown.get("raw_markdown") or "").strip()
        final_url = result.get("redirected_url") or url
        title = (result.get("metadata") or {}).get("title")
        status = result.get("status_code")
        reason = str(result.get("error_message") or "").strip().splitlines()[:1]
    except (ValueError, LookupError, TypeError, AttributeError) as exc:
        raise RenderError("The page renderer gave an answer that could not be read") from exc

    if not success:
        why = reason[0][:200] if reason else "no reason given"
        raise RenderError(f"The page did not load in the browser ({why}); paste the text instead")
    try:
        await public_address(httpx.URL(final_url))
    except BlockedUrlError:
        raise BlockedUrlError("This link leads to a private or local network, which is not allowed") from None
    if isinstance(status, int) and status >= 400:
        raise RenderError(f"The site answered with an error (HTTP {status})")
    if len(text) < MIN_TEXT_CHARS:
        raise ExtractionError(
            "Could not find readable text on this page, even in a browser. "
            "It may need a login or check for robots; paste the text instead"
        )
    return Page(url=final_url, title=title.strip() if isinstance(title, str) and title.strip() else None, text=text)
