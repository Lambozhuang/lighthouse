"""Fetching a page: the SSRF guard first, then limits and text extraction.

Nothing here touches the network. HTTP goes to an `httpx.MockTransport`, and DNS is replaced by a
table the test fills in.
"""

import ipaddress
import socket
from collections.abc import Callable

import httpx
import pytest

from lighthouse.ingest import fetch

pytestmark = pytest.mark.asyncio(loop_scope="session")

PUBLIC_IP = "93.184.216.34"
ARTICLE = (
    "<html><head><title>Why sleep matters</title></head><body><nav>Home | About</nav><article>"
    "<h1>Why sleep matters</h1><p>" + "Sleep helps the brain consolidate memories. " * 15 + "</p>"
    "</article><footer>Copyright</footer></body></html>"
)
real_resolve = fetch.resolve


@pytest.fixture(autouse=True)
def dns(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[str]]:
    """Fake DNS. Tests add `hostname -> addresses`; an IP literal resolves to itself."""
    table: dict[str, list[str]] = {}

    async def resolve(host: str) -> list[str]:
        if host in table:
            return table[host]
        try:
            return [str(ipaddress.ip_address(host))]
        except ValueError:
            raise socket.gaierror(socket.EAI_NONAME, "unknown host") from None

    monkeypatch.setattr(fetch, "resolve", resolve)
    return table


class Site:
    """A mock transport that records the requests it receives."""

    def __init__(self, handler: Callable[[httpx.Request], httpx.Response]) -> None:
        self.requests: list[httpx.Request] = []
        self._handler = handler
        self.transport = httpx.MockTransport(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self._handler(request)


def html(body: str = ARTICLE, status: int = 200) -> httpx.Response:
    return httpx.Response(status, headers={"content-type": "text/html; charset=utf-8"}, content=body.encode())


# --- the guard ---


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/",
        "http://127.0.0.1:8080/admin",
        "http://10.0.0.8/",
        "http://172.16.0.1/",
        "http://192.168.1.1/router",
        "http://169.254.169.254/latest/meta-data/",  # cloud metadata service
        "http://100.64.0.1/",  # carrier-grade NAT range (Tailscale addresses)
        "http://0.0.0.0/",
        "http://224.0.0.1/",  # multicast
        "http://240.0.0.1/",  # reserved
        "http://[::1]/",
        "http://[::]/",
        "http://[fe80::1]/",
        "http://[fc00::1]/",
        "http://[ff02::1]/",
        "http://[::ffff:127.0.0.1]/",  # IPv4-mapped IPv6
        "http://[::ffff:192.168.1.1]/",
        "http://[64:ff9b::7f00:1]/",  # NAT64 prefix wrapping 127.0.0.1
    ],
)
async def test_private_ip_literals_are_blocked(url: str) -> None:
    site = Site(lambda request: html())
    with pytest.raises(fetch.BlockedUrlError):
        await fetch.fetch_page(url, transport=site.transport)
    assert site.requests == [], "a blocked address must never be contacted"


@pytest.mark.parametrize("url", ["ftp://example.com/file", "file:///etc/passwd", "gopher://example.com/", "http://"])
async def test_only_http_and_https(url: str) -> None:
    site = Site(lambda request: html())
    with pytest.raises(fetch.BlockedUrlError):
        await fetch.fetch_page(url, transport=site.transport)
    assert site.requests == []


async def test_malformed_url_is_refused() -> None:
    with pytest.raises(fetch.BlockedUrlError, match="not a valid web address"):
        await fetch.fetch_page("http://[::1", transport=Site(lambda request: html()).transport)


@pytest.mark.parametrize("addresses", [["10.0.0.5"], ["::1"], [PUBLIC_IP, "192.168.1.20"]])
async def test_hostname_resolving_to_a_private_address_is_blocked(
    dns: dict[str, list[str]], addresses: list[str]
) -> None:
    dns["intranet.example"] = addresses
    site = Site(lambda request: html())
    with pytest.raises(fetch.BlockedUrlError):
        await fetch.fetch_page("https://intranet.example/wiki", transport=site.transport)
    assert site.requests == []


async def test_redirect_to_a_private_address_is_blocked(dns: dict[str, list[str]]) -> None:
    dns["public.example"] = [PUBLIC_IP]
    site = Site(lambda request: httpx.Response(302, headers={"location": "http://169.254.169.254/latest/meta-data/"}))
    with pytest.raises(fetch.BlockedUrlError):
        await fetch.fetch_page("http://public.example/start", transport=site.transport)
    assert len(site.requests) == 1, "only the public first hop may be contacted"


async def test_redirect_to_a_hostname_with_a_private_address_is_blocked(dns: dict[str, list[str]]) -> None:
    dns["public.example"] = [PUBLIC_IP]
    dns["rebind.example"] = ["127.0.0.1"]
    site = Site(lambda request: httpx.Response(301, headers={"location": "https://rebind.example/"}))
    with pytest.raises(fetch.BlockedUrlError):
        await fetch.fetch_page("http://public.example/", transport=site.transport)
    assert len(site.requests) == 1


async def test_connection_goes_to_the_checked_address(dns: dict[str, list[str]]) -> None:
    """The request is sent to the IP that passed the check, with the site named in Host and SNI."""
    dns["blog.example"] = [PUBLIC_IP, "93.184.216.35"]
    site = Site(lambda request: html())
    await fetch.fetch_page("https://blog.example:8443/post?id=1", transport=site.transport)

    (request,) = site.requests
    assert str(request.url) == f"https://{PUBLIC_IP}:8443/post?id=1"
    assert request.headers["host"] == "blog.example:8443"
    assert request.extensions["sni_hostname"] == "blog.example"


async def test_resolve_returns_ip_literals_unchanged() -> None:
    # The real resolver, on literals only (no DNS query is made for these).
    assert await real_resolve("127.0.0.1") == ["127.0.0.1"]
    assert await real_resolve("::1") == ["::1"]


# --- following redirects ---


async def test_follows_redirects_and_reports_the_final_url(dns: dict[str, list[str]]) -> None:
    dns["short.example"] = [PUBLIC_IP]
    dns["blog.example"] = ["93.184.216.35"]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.headers["host"] == "short.example":
            return httpx.Response(301, headers={"location": "https://blog.example/posts/sleep"})
        if request.url.path == "/posts/sleep":
            return httpx.Response(302, headers={"location": "/posts/why-sleep-matters"})  # relative
        return html()

    site = Site(handler)
    page = await fetch.fetch_page("http://short.example/abc", transport=site.transport)

    assert page.url == "https://blog.example/posts/why-sleep-matters"
    assert [request.url.host for request in site.requests] == [PUBLIC_IP, "93.184.216.35", "93.184.216.35"]


async def test_too_many_redirects(dns: dict[str, list[str]]) -> None:
    dns["loop.example"] = [PUBLIC_IP]
    site = Site(lambda request: httpx.Response(302, headers={"location": "/again"}))
    with pytest.raises(fetch.TooManyRedirectsError):
        await fetch.fetch_page("http://loop.example/", transport=site.transport)
    assert len(site.requests) == fetch.MAX_REDIRECTS + 1


# --- extraction and limits ---


async def test_extracts_title_and_main_text(dns: dict[str, list[str]]) -> None:
    dns["blog.example"] = [PUBLIC_IP]
    page = await fetch.fetch_page("https://blog.example/sleep", transport=Site(lambda request: html()).transport)

    assert page.title == "Why sleep matters"
    assert "Sleep helps the brain consolidate memories." in page.text
    assert "Copyright" not in page.text and "Home | About" not in page.text


async def test_chinese_page_without_a_declared_charset(dns: dict[str, list[str]]) -> None:
    dns["zh.example"] = [PUBLIC_IP]
    body = (
        "<html><head><title>睡眠的重要性</title></head><body><article><h1>睡眠的重要性</h1><p>"
        + "充足的睡眠有助于巩固记忆，这一点已被多项研究证实。" * 12
        + "</p></article></body></html>"
    )
    response = httpx.Response(200, headers={"content-type": "text/html"}, content=body.encode("gb18030"))
    page = await fetch.fetch_page("https://zh.example/", transport=Site(lambda request: response).transport)

    assert page.title == "睡眠的重要性"
    assert "充足的睡眠有助于巩固记忆" in page.text


async def test_plain_text_is_taken_as_is(dns: dict[str, list[str]]) -> None:
    dns["raw.example"] = [PUBLIC_IP]
    text = "# Notes\n\n" + "A line of plain text notes.\n" * 20
    response = httpx.Response(200, headers={"content-type": "text/plain; charset=utf-8"}, content=text.encode())
    page = await fetch.fetch_page("https://raw.example/notes.md", transport=Site(lambda request: response).transport)

    assert page.title is None
    assert page.text == text.strip()


async def test_page_without_readable_text(dns: dict[str, list[str]]) -> None:
    dns["app.example"] = [PUBLIC_IP]
    shell = "<html><head><title>App</title></head><body><div id='root'></div><script>boot()</script></body></html>"
    with pytest.raises(fetch.ExtractionError, match="paste the text instead"):
        await fetch.fetch_page("https://app.example/", transport=Site(lambda request: html(shell)).transport)


async def test_non_html_content_is_rejected(dns: dict[str, list[str]]) -> None:
    dns["files.example"] = [PUBLIC_IP]
    response = httpx.Response(200, headers={"content-type": "application/pdf"}, content=b"%PDF-1.7")
    with pytest.raises(fetch.UnsupportedContentError, match="application/pdf"):
        await fetch.fetch_page("https://files.example/paper.pdf", transport=Site(lambda request: response).transport)


async def test_oversized_page_is_rejected(dns: dict[str, list[str]], monkeypatch: pytest.MonkeyPatch) -> None:
    dns["big.example"] = [PUBLIC_IP]
    monkeypatch.setattr(fetch, "MAX_BYTES", 1024)
    with pytest.raises(fetch.PageTooLargeError):
        await fetch.fetch_page("https://big.example/", transport=Site(lambda request: html(ARTICLE * 5)).transport)


@pytest.mark.parametrize(("status", "retryable"), [(404, False), (403, False), (429, True), (503, True)])
async def test_http_errors(dns: dict[str, list[str]], status: int, retryable: bool) -> None:
    dns["blog.example"] = [PUBLIC_IP]
    with pytest.raises(fetch.HttpStatusError, match=str(status)) as raised:
        await fetch.fetch_page("https://blog.example/", transport=Site(lambda request: html("gone", status)).transport)
    assert raised.value.retryable is retryable


async def test_network_failures_are_retryable(dns: dict[str, list[str]]) -> None:
    dns["down.example"] = [PUBLIC_IP]

    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    with pytest.raises(fetch.NetworkError) as raised:
        await fetch.fetch_page("https://down.example/", transport=Site(refuse).transport)
    assert raised.value.retryable

    with pytest.raises(fetch.NetworkError, match="DNS"):  # not in the fake DNS table
        await fetch.fetch_page("https://no-such-host.example/", transport=Site(refuse).transport)


async def test_slow_page_times_out(dns: dict[str, list[str]], monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio

    dns["slow.example"] = [PUBLIC_IP]
    monkeypatch.setattr(fetch, "TOTAL_TIMEOUT_SECONDS", 0.05)

    async def stall(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(5)
        return html()

    with pytest.raises(fetch.NetworkError, match="too long"):
        await fetch.fetch_page("https://slow.example/", transport=httpx.MockTransport(stall))
