"""HTML parser — stdlib only, no DB writes, no network calls."""

from __future__ import annotations

import re
from html.parser import HTMLParser

from .models import ParsedResult
from .url_normalizer import canonicalize_url

# Tags whose text content should be silently dropped.
_SKIP_TAGS = frozenset({"script", "style", "noscript", "template"})

# Regex for tokenization: one or more word characters, minimum 2 chars.
_TOKEN_RE = re.compile(r"[a-z]{2,}", re.ASCII)


# ---------------------------------------------------------------------------
# Internal SAX-style collector
# ---------------------------------------------------------------------------


class _Collector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title: str | None = None
        self._in_title = False
        self._title_buf: list[str] = []
        self._skip_depth = 0          # >0 means we are inside a skip tag
        self._text_parts: list[str] = []
        self.hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
            return
        if tag == "title" and self._skip_depth == 0:
            self._in_title = True
        if tag == "a" and self._skip_depth == 0:
            for name, value in attrs:
                if name.lower() == "href" and value:
                    self.hrefs.append(value.strip())

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in _SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._skip_depth > 0:
            return
        if self._in_title:
            self._title_buf.append(data)
            return
        stripped = data.strip()
        if stripped:
            self._text_parts.append(stripped)

    # ------------------------------------------------------------------

    def result(self) -> tuple[str | None, str]:
        title = "".join(self._title_buf).strip() or None
        visible = " ".join(self._text_parts)
        return title, visible


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


def parse_html(html_text: str, base_url: str) -> ParsedResult:
    collector = _Collector()
    collector.feed(html_text)
    title, visible_text = collector.result()

    seen: set[str] = set()
    outgoing_urls: list[str] = []
    for raw in collector.hrefs:
        canonical = canonicalize_url(raw, base_url=base_url)
        if canonical and canonical not in seen:
            seen.add(canonical)
            outgoing_urls.append(canonical)

    tokens = _tokenize((title or "") + " " + visible_text)

    return ParsedResult(
        title=title,
        visible_text=visible_text,
        tokens=tokens,
        outgoing_urls=outgoing_urls,
    )
