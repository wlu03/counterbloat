"""Server-side fetcher that refuses private destinations and oversized or unexpected content."""
from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urljoin, urlparse

import httpx

MAX_BYTES = 20_000_000
MAX_REDIRECTS = 5
ALLOWED_TYPES = ("text/html", "application/xhtml+xml", "text/plain", "application/pdf")


class BlockedDestination(Exception):
    pass


class FetchError(Exception):
    pass


def validate_url(url: str) -> None:
    """Raise unless the URL is http(s) and every address it resolves to is public."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise BlockedDestination(f"scheme or host not allowed: {url}")
    try:
        infos = socket.getaddrinfo(parsed.hostname, None)
    except socket.gaierror as exc:
        raise FetchError(f"cannot resolve {parsed.hostname}") from exc
    for info in infos:
        address = ipaddress.ip_address(info[4][0])
        # is_global is false for private, loopback, link-local, and metadata addresses.
        if not address.is_global:
            raise BlockedDestination(f"{parsed.hostname} resolves to {address}")


def fetch(url: str) -> tuple[bytes, str, str]:
    """Return (content, media type, final URL). Each redirect target is validated again."""
    with httpx.Client(follow_redirects=False, timeout=30) as client:
        for _ in range(MAX_REDIRECTS + 1):
            validate_url(url)
            with client.stream("GET", url, headers={"User-Agent": "Countercheck/0.1"}) as response:
                if response.is_redirect:
                    url = urljoin(url, response.headers["location"])
                    continue
                if response.status_code != 200:
                    raise FetchError(f"{url} returned {response.status_code}")
                media_type = response.headers.get("content-type", "").split(";")[0].strip()
                if media_type not in ALLOWED_TYPES:
                    raise FetchError(f"content type not allowed: {media_type}")
                content = b""
                for chunk in response.iter_bytes():
                    content += chunk
                    if len(content) > MAX_BYTES:
                        raise FetchError("content exceeds size limit")
                return content, media_type, url
    raise FetchError("too many redirects")
