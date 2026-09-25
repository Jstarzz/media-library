import ipaddress
import socket
from urllib.parse import urljoin, urlparse, urlunparse

import httpx

from app.config import get_settings


BLOCKED_HOSTS = {"localhost", "localhost.localdomain", "metadata.google.internal"}


def normalize_url(url: str) -> str:
    parsed = urlparse(url.strip())
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("Only http/https URLs are allowed")
    if not parsed.hostname:
        raise ValueError("URL has no hostname")
    netloc = parsed.hostname.lower()
    if parsed.port:
        netloc += f":{parsed.port}"
    path = parsed.path or "/"
    return urlunparse((parsed.scheme.lower(), netloc, path, "", parsed.query, ""))


def _address_is_public(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    return not (
        ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast
        or ip.is_reserved or ip.is_unspecified
    )


def validate_public_url(url: str) -> str:
    normalized = normalize_url(url)
    parsed = urlparse(normalized)
    hostname = parsed.hostname.lower()
    if hostname in BLOCKED_HOSTS:
        raise ValueError("Local/internal hosts are blocked")

    try:
        addresses = socket.getaddrinfo(hostname, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ValueError(f"Could not resolve host: {hostname}") from exc

    ips = {entry[4][0] for entry in addresses}
    if not ips or any(not _address_is_public(ip) for ip in ips):
        raise ValueError("URL resolves to a blocked network range")
    return normalized


async def safe_get(url: str, *, max_bytes: int | None = None, accept: str = "*/*") -> httpx.Response:
    settings = get_settings()
    current = validate_public_url(url)
    max_bytes = max_bytes or settings.max_html_mb * 1024 * 1024

    async with httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=8.0), follow_redirects=False) as client:
        for _ in range(6):
            response = await client.get(current, headers={"User-Agent": "MediaLibrary/0.1", "Accept": accept})
            if response.status_code in {301, 302, 303, 307, 308}:
                location = response.headers.get("location")
                if not location:
                    raise ValueError("Redirect did not include Location")
                current = validate_public_url(urljoin(current, location))
                continue
            response.raise_for_status()
            if len(response.content) > max_bytes:
                raise ValueError(f"Response exceeds {max_bytes} bytes")
            return response
    raise ValueError("Too many redirects")
