"""Write-path for one processed page.

Designed to sit behind a single writer thread later; currently called
synchronously from Coordinator.step().
"""

from __future__ import annotations

import collections
import hashlib
import sqlite3
from datetime import datetime, timezone

from .frontier import Frontier
from .models import FetchOutcome, FetchResult, FrontierItem, FetchState, ParsedResult
from .storage import (
    get_or_create_page,
    get_page_fetch_state,
    set_page_fetch_state,
    update_page_fetched,
    replace_page_links,
    replace_postings,
    upsert_discovery,
    get_job_max_depth,
)


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def _term_frequencies(tokens: list[str]) -> dict[str, int]:
    return dict(collections.Counter(tokens))


def persist_page(
    conn: sqlite3.Connection,
    frontier: Frontier,
    *,
    item: FrontierItem,
    fetch_result: FetchResult,
    parsed: ParsedResult | None,
) -> int:
    """Persist one processed page and admit eligible children.

    Returns the number of children admitted to the frontier.
    """
    now = datetime.now(timezone.utc).isoformat()
    children_admitted = 0

    if fetch_result.outcome == FetchOutcome.HTML_SUCCESS and parsed is not None:
        body = fetch_result.body or ""
        update_page_fetched(
            conn,
            page_id=item.page_id,
            fetch_state=FetchState.FETCHED.value,
            http_status=fetch_result.http_status,
            content_type=fetch_result.content_type,
            title=parsed.title,
            content_hash=_content_hash(body),
            fetched_at=now,
        )

        # page_links + postings
        target_ids: list[int] = []
        for url in parsed.outgoing_urls:
            child_id, _ = get_or_create_page(conn, url)
            target_ids.append(child_id)
        replace_page_links(conn, item.page_id, target_ids)

        replace_postings(conn, item.page_id, _term_frequencies(parsed.tokens))

        # child admission
        child_depth = item.depth + 1
        max_depth = get_job_max_depth(conn, item.job_id)
        if max_depth is not None and child_depth <= max_depth:
            for url, child_id in zip(parsed.outgoing_urls, target_ids):
                upsert_discovery(
                    conn,
                    job_id=item.job_id,
                    page_id=child_id,
                    depth=child_depth,
                    parent_page_id=item.page_id,
                    discovered_at=now,
                )
                state = get_page_fetch_state(conn, child_id)
                if state == FetchState.UNFETCHED.value:
                    child_item = FrontierItem(
                        url=url,
                        job_id=item.job_id,
                        depth=child_depth,
                        page_id=child_id,
                        parent_page_id=item.page_id,
                    )
                    if frontier.admit(child_item):
                        set_page_fetch_state(conn, child_id, FetchState.QUEUED.value)
                        children_admitted += 1

    else:
        # Non-HTML or error: record outcome, no links/postings.
        error_state = (
            FetchState.FAILED.value
            if fetch_result.outcome in (
                FetchOutcome.HTTP_ERROR,
                FetchOutcome.NETWORK_ERROR,
                FetchOutcome.INVALID_INPUT,
            )
            else FetchState.FETCHED.value  # non-html counts as fetched
        )
        update_page_fetched(
            conn,
            page_id=item.page_id,
            fetch_state=error_state,
            http_status=fetch_result.http_status,
            content_type=fetch_result.content_type,
            title=None,
            content_hash=None,
            fetched_at=now,
        )

    return children_admitted
