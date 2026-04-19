"""Synchronous HTTP fetcher — stdlib only, no parsing, no DB writes."""

from __future__ import annotations

import re
import urllib.error
import urllib.request
from urllib.parse import urlparse

from .models import FetchOutcome, FetchResult

_DEFAULT_TIMEOUT = 10.0
_DEFAULT_MAX_BYTES = 2 * 1024 * 1024  # 2 MB
_DEFAULT_USER_AGENT = "crawler-search/0.1"

_CHARSET_RE = re.compile(r"charset=([^\s;]+)", re.IGNORECASE)
_HTML_MIME_RE = re.compile(r"text/html", re.IGNORECASE)


def _is_http(url: str) -> bool:
    scheme = urlparse(url).scheme.lower()
    return scheme in ("http", "https")


def _parse_charset(content_type: str) -> str | None:
    m = _CHARSET_RE.search(content_type)
    return m.group(1).strip('"') if m else None


def _decode_body(raw: bytes, content_type: str | None) -> str:
    charset: str | None = None
    if content_type:
        charset = _parse_charset(content_type)
    if charset:
        try:
            return raw.decode(charset, errors="replace")
        except LookupError:
            pass
    # UTF-8 with replacement is a safe universal fallback.
    return raw.decode("utf-8", errors="replace")


def fetch_url(
    url: str,
    *,
    timeout: float = _DEFAULT_TIMEOUT,
    max_bytes: int = _DEFAULT_MAX_BYTES,
    user_agent: str = _DEFAULT_USER_AGENT,
) -> FetchResult:
    """Fetch *url* and return a structured FetchResult.

    Does not parse links, does not write to DB.
    Redirects are followed by urllib automatically.
    """
    if not url or not _is_http(url):
        return FetchResult(
            requested_url=url,
            final_url=url,
            outcome=FetchOutcome.INVALID_INPUT,
            error=f"unsupported scheme or empty URL: {url!r}",
        )

    req = urllib.request.Request(url, headers={"User-Agent": user_agent})

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            final_url: str = resp.url or url
            http_status: int = resp.status
            content_type: str | None = resp.headers.get("Content-Type")

            raw = resp.read(max_bytes)

    except urllib.error.HTTPError as exc:
        return FetchResult(
            requested_url=url,
            final_url=url,
            outcome=FetchOutcome.HTTP_ERROR,
            http_status=exc.code,
            error=str(exc.reason),
        )
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        return FetchResult(
            requested_url=url,
            final_url=url,
            outcome=FetchOutcome.NETWORK_ERROR,
            error=str(exc),
        )

    is_html = bool(content_type and _HTML_MIME_RE.search(content_type))

    if not is_html:
        return FetchResult(
            requested_url=url,
            final_url=final_url,
            outcome=FetchOutcome.NON_HTML,
            http_status=http_status,
            content_type=content_type,
        )

    body = _decode_body(raw, content_type)
    return FetchResult(
        requested_url=url,
        final_url=final_url,
        outcome=FetchOutcome.HTML_SUCCESS,
        http_status=http_status,
        content_type=content_type,
        body=body,
    )
