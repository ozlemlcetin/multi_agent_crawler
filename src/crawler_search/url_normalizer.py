"""Canonical URL normalization — stdlib only, no network calls."""

from __future__ import annotations

import re
from urllib.parse import urlparse, urlunparse, urljoin, ParseResult

_ALLOWED_SCHEMES = frozenset({"http", "https"})
_DEFAULT_PORTS = {"http": 80, "https": 443}
_MULTI_SLASH = re.compile(r"/{2,}")


def canonicalize_url(url: str, base_url: str | None = None) -> str | None:
    """Return a canonical URL string, or None if the URL is unsupported/invalid."""
    if not url or not url.strip():
        return None

    url = url.strip()

    # Resolve relative URLs before any other processing.
    if base_url:
        url = urljoin(base_url, url)

    try:
        p: ParseResult = urlparse(url)
    except Exception:
        return None

    scheme = p.scheme.lower()
    if scheme not in _ALLOWED_SCHEMES:
        return None

    host = p.hostname
    if not host:
        return None
    host = host.lower()

    # Rebuild netloc: drop port if it is the scheme default.
    port = p.port
    if port and port != _DEFAULT_PORTS.get(scheme):
        netloc = f"{host}:{port}"
    else:
        netloc = host

    # Include userinfo if present (uncommon but valid).
    if p.username:
        userinfo = p.username + (f":{p.password}" if p.password else "")
        netloc = f"{userinfo}@{netloc}"

    path = p.path or "/"
    # Collapse runs of slashes that are not at the start (preserve leading /).
    path = "/" + _MULTI_SLASH.sub("/", path.lstrip("/"))
    # Remove trailing slash unless path is exactly "/".
    if path != "/":
        path = path.rstrip("/")

    # Drop fragment; preserve query as-is.
    return urlunparse((scheme, netloc, path, "", p.query, ""))
