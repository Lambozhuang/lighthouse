"""From a dropped link to its text: picks the way to read it.

    YouTube video  →  its captions                        (youtube.py)
    anything else  →  one plain HTTP request              (fetch.py; web pages, text files, PDFs)
                      if that finds no text or is refused, and a renderer is configured:
                   →  the same page in a headless browser (render.py)

The plain request comes first because it is fast (about a second, no browser) and enough for
most articles. The browser is the fallback for pages built with JavaScript.
"""

import logging

from lighthouse.ingest import fetch, render, youtube
from lighthouse.ingest.fetch import Page

log = logging.getLogger(__name__)

# Statuses that mean "there is nothing here" or "slow down". A browser would get the same answer.
NOT_WORTH_RENDERING = {404, 410, 429}


async def read_url(url: str) -> Page:
    video = youtube.video_id(url)
    if video is not None:
        return await youtube.fetch_video(video)
    try:
        return await fetch.fetch_page(url)
    except fetch.FetchError as plain_error:
        if not (render.enabled() and worth_rendering(plain_error)):
            raise
        log.info("plain fetch of %s failed (%s); trying the renderer", url, plain_error)
        return await render.render_page(url)


def worth_rendering(error: fetch.FetchError) -> bool:
    """Could a real browser succeed where the plain request failed with `error`?"""
    if isinstance(error, fetch.ExtractionError):
        return True  # the page loaded but had no text in its HTML: built with JavaScript
    if isinstance(error, fetch.HttpStatusError):
        # 4xx: the site turned the plain client away (403 and the like). 5xx is the site's own
        # trouble; the worker retries those.
        return 400 <= error.status < 500 and error.status not in NOT_WORTH_RENDERING
    return False
