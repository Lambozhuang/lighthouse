"""YouTube links: recognising them and turning captions into text. YouTube itself is not called."""

import pytest
from youtube_transcript_api import FetchedTranscript, FetchedTranscriptSnippet

from lighthouse.ingest import fetch, youtube

pytestmark = pytest.mark.asyncio(loop_scope="session")

VIDEO = "dQw4w9WgXcQ"


def transcript(*lines: tuple[float, str]) -> FetchedTranscript:
    return FetchedTranscript(
        snippets=[FetchedTranscriptSnippet(text=text, start=start, duration=2.0) for start, text in lines],
        video_id=VIDEO,
        language="English",
        language_code="en",
        is_generated=False,
    )


@pytest.mark.parametrize(
    "url",
    [
        f"https://www.youtube.com/watch?v={VIDEO}",
        f"https://youtube.com/watch?v={VIDEO}&t=42s",
        f"https://m.youtube.com/watch?list=PL123&v={VIDEO}",
        f"https://youtu.be/{VIDEO}?si=abc",
        f"https://www.youtube.com/shorts/{VIDEO}",
        f"https://www.youtube.com/embed/{VIDEO}",
        f"https://www.youtube.com/live/{VIDEO}",
    ],
)
async def test_video_links_are_recognised(url: str) -> None:
    assert youtube.video_id(url) == VIDEO


@pytest.mark.parametrize(
    "url",
    [
        "https://www.youtube.com/",
        "https://www.youtube.com/@somechannel",
        "https://www.youtube.com/playlist?list=PL123",
        "https://www.youtube.com/watch?v=short",
        f"https://youtube.com.evil.example/watch?v={VIDEO}",
        f"https://example.com/watch?v={VIDEO}",
        f"ftp://youtu.be/{VIDEO}",
        "not a url",
    ],
)
async def test_other_links_are_not_videos(url: str) -> None:
    assert youtube.video_id(url) is None


async def test_captions_become_paragraphs_with_timestamps() -> None:
    text = youtube.format_transcript(
        transcript(
            (0.0, "hi  everyone"), (3.0, "today we talk\nabout sleep"), (61.0, "first point"), (3725.0, "the end")
        )
    )
    assert text == "[0:00] hi everyone today we talk about sleep\n\n[1:01] first point\n\n[1:02:05] the end"


async def test_fetch_video(monkeypatch: pytest.MonkeyPatch) -> None:
    async def title(url: str) -> str | None:
        return "Why we sleep (Some Channel)"

    monkeypatch.setattr(youtube, "_transcript", lambda video: transcript((0.0, "sleep matters"), (2.0, "a lot")))
    monkeypatch.setattr(youtube, "_title", title)
    page = await youtube.fetch_video(VIDEO)

    assert page.url == f"https://www.youtube.com/watch?v={VIDEO}"
    assert page.title == "Why we sleep (Some Channel)"
    assert page.text == "[0:00] sleep matters a lot"


async def test_video_without_captions(monkeypatch: pytest.MonkeyPatch) -> None:
    from youtube_transcript_api import TranscriptsDisabled, YouTubeTranscriptApi

    def no_captions(self: YouTubeTranscriptApi, video: str) -> None:
        raise TranscriptsDisabled(video)

    async def title(url: str) -> str | None:
        return None

    monkeypatch.setattr(YouTubeTranscriptApi, "list", no_captions)
    monkeypatch.setattr(youtube, "_title", title)
    with pytest.raises(fetch.ExtractionError, match="no captions") as raised:
        await youtube.fetch_video(VIDEO)
    assert not raised.value.retryable
