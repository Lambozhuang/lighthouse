"""Fetch a web page and pull out its main text.

The URL comes from whoever dropped it, and the worker runs inside the home network. Without a
guard, dropping `http://192.168.1.1/admin` or a cloud metadata address would make the worker read
it from the inside and file the answer as a note: server-side request forgery (SSRF). The guard:

1. Only `http` and `https`.
2. The hostname is resolved here, and every address it resolves to must be public. The connection
   is then made to that checked address, not to the hostname, so a DNS server cannot answer
   "public" for the check and "private" for the connection (DNS rebinding).
3. Redirects are followed by hand, at most 5, and each hop goes through steps 1 and 2 again.
4. Time, size and content type are capped.

What it does not cover: "public" is what Python's `ipaddress` module says is public. A LAN device
with a global IPv6 address, or the router's own public address, passes the check. Closing that
needs a network-level rule (run the worker where it cannot reach the LAN), not more code here.
"""

import asyncio
import ipaddress
import socket
from dataclasses import dataclass

import httpx
import trafilatura
from trafilatura.settings import Document

from lighthouse.ingest.errors import IngestError

MAX_REDIRECTS = 5
MAX_BYTES = 5 * 1024 * 1024  # counted after decompression
TOTAL_TIMEOUT_SECONDS = 15  # for the whole download, redirects included
MIN_TEXT_CHARS = 200  # less than this is a cookie banner or an empty app shell, not an article
HTML_TYPES = {"text/html", "application/xhtml+xml"}
# A generic name: sites that turn away unknown clients mostly accept this form.
USER_AGENT = "Mozilla/5.0 (compatible; notes-fetcher/0.1)"


@dataclass(frozen=True)
class Page:
    url: str  # where the content finally came from, after redirects
    title: str | None
    text: str  # main content as Markdown


class FetchError(IngestError):
    """Base class for everything that can go wrong here. Messages are shown to the user."""


class BlockedUrlError(FetchError):
    """The SSRF guard said no."""


class NetworkError(FetchError):
    """DNS failure, connection error or timeout. Might work next time."""

    retryable = True


class HttpStatusError(FetchError):
    def __init__(self, status: int) -> None:
        super().__init__(f"The site answered with an error (HTTP {status})")
        self.retryable = status == 429 or status >= 500  # rate limit or server trouble


class TooManyRedirectsError(FetchError):
    pass


class UnsupportedContentError(FetchError):
    pass


class PageTooLargeError(FetchError):
    pass


class ExtractionError(FetchError):
    """The page loaded but has no article text in its HTML."""


async def fetch_page(url: str, *, transport: httpx.AsyncBaseTransport | None = None) -> Page:
    """Download `url` and extract title and main text. `transport` is for tests."""
    try:
        async with asyncio.timeout(TOTAL_TIMEOUT_SECONDS):
            page = await _download(url, transport)
    except TimeoutError:
        raise NetworkError("The page took too long to load") from None
    except httpx.InvalidURL:
        raise BlockedUrlError("This is not a valid web address") from None
    except httpx.HTTPError as exc:
        raise NetworkError(f"Could not reach the site ({type(exc).__name__})") from exc
    # Parsing a large page takes a moment of pure CPU work; keep it off the event loop.
    return await asyncio.to_thread(_extract, page)


@dataclass(frozen=True)
class _Download:
    url: str
    media_type: str
    charset: str | None  # from the Content-Type header, if it named one
    body: bytes


async def _download(url: str, transport: httpx.AsyncBaseTransport | None) -> _Download:
    # trust_env=False: ignore proxy settings from the environment. A proxy would resolve the
    # hostname itself, which defeats the address check below.
    async with httpx.AsyncClient(
        transport=transport,
        timeout=10,
        trust_env=False,
        headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml,text/plain;q=0.8"},
    ) as client:
        current = httpx.URL(url)
        for _ in range(MAX_REDIRECTS + 1):
            address = await public_address(current)
            # Connect to the checked address, and say which site is meant in the Host header and
            # in the TLS handshake (`sni_hostname` is also the name the certificate is checked
            # against). To the client every site is now "an IP address", so drop cookies between
            # hops or it would hand one site's cookies to another on the same address.
            client.cookies.clear()
            async with client.stream(
                "GET",
                current.copy_with(host=address),
                headers={"Host": current.netloc.decode("ascii")},
                extensions={"sni_hostname": current.raw_host.decode("ascii")},
            ) as response:
                if response.has_redirect_location:
                    current = current.join(response.headers["location"])
                    continue
                if not response.is_success:
                    raise HttpStatusError(response.status_code)
                media_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
                if media_type not in HTML_TYPES and media_type != "text/plain":
                    raise UnsupportedContentError(
                        f"Only web pages can be filed; this link is {media_type or 'an unknown kind of file'}"
                    )
                body = await _read_capped(response)
                return _Download(str(current), media_type, response.charset_encoding, body)
        raise TooManyRedirectsError(f"The link redirects more than {MAX_REDIRECTS} times")


async def public_address(url: httpx.URL) -> str:
    """The SSRF check: the IP address to connect to for `url`, or BlockedUrlError."""
    if url.scheme not in ("http", "https") or not url.host:
        raise BlockedUrlError("Only http:// and https:// links can be fetched")
    try:
        addresses = await resolve(url.raw_host.decode("ascii"))
    except OSError:
        raise NetworkError("Could not find this site (DNS lookup failed)") from None
    # All of them, not just the one we will use: a name that mixes public and private
    # addresses is not a site we want to talk to.
    if not addresses or not all(is_public(address) for address in addresses):
        raise BlockedUrlError("This address points to a private or local network, which is not allowed")
    return addresses[0]


async def resolve(host: str) -> list[str]:
    """Every address `host` resolves to. An IP literal, in any spelling the system accepts
    (`127.1`, `2130706433`), comes back as that IP, so odd spellings are checked like any other."""
    infos = await asyncio.get_running_loop().getaddrinfo(host, None, type=socket.SOCK_STREAM)
    return [str(info[4][0]) for info in infos]


def is_public(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    # `::ffff:10.0.0.1` is the IPv4 address 10.0.0.1 written as IPv6; judge the address inside.
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    blocked = (
        ip.is_loopback  # 127.0.0.0/8, ::1
        or ip.is_private  # 10/8, 172.16/12, 192.168/16, fc00::/7
        or ip.is_link_local  # 169.254/16 (cloud metadata lives here), fe80::/10
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified  # 0.0.0.0, ::
        or not ip.is_global  # the rest, e.g. 100.64.0.0/10 (carrier-grade NAT, used by Tailscale)
    )
    return not blocked


async def _read_capped(response: httpx.Response) -> bytes:
    body = bytearray()
    async for chunk in response.aiter_bytes():
        body += chunk
        if len(body) > MAX_BYTES:
            raise PageTooLargeError(f"The page is larger than {MAX_BYTES // (1024 * 1024)} MB")
    return bytes(body)


def _extract(page: _Download) -> Page:
    html = _decode(page.body, page.charset)
    title: str | None = None
    text = ""
    if page.media_type == "text/plain":
        text = html.strip()
    else:
        # trafilatura keeps the article and drops navigation, ads and footers.
        # include_formatting gives Markdown (headings, lists) instead of flat text.
        document = trafilatura.bare_extraction(
            html, url=page.url, with_metadata=True, include_formatting=True, include_comments=False
        )
        if isinstance(document, Document):
            title, text = document.title, (document.text or "").strip()
    if len(text) < MIN_TEXT_CHARS:
        raise ExtractionError(
            "Could not find readable text on this page. It may need JavaScript or a login; paste the text instead"
        )
    return Page(url=page.url, title=title or None, text=text)


def _decode(body: bytes, charset: str | None) -> str:
    """Use the charset from the Content-Type header if there is one, else let trafilatura guess."""
    if charset:
        try:
            return body.decode(charset, errors="replace")
        except LookupError:  # the server named an encoding Python does not know
            pass
    return trafilatura.utils.decode_file(body)
