"""Coordinator — threading comes in a later patch."""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone

from .config import Config, DEFAULT_CONFIG
from .fetcher import fetch_url
from .frontier import Frontier
from .index_writer import persist_page
from .models import (
    CrawlJob, FrontierItem, FetchState, FetchOutcome,
    JobStatus, StepResult,
)
from .search_service import search as db_search, SearchRow
from .parser import parse_html
from .storage import (
    open_db,
    insert_crawl_job,
    list_crawl_jobs,
    count_crawl_jobs,
    get_or_create_page,
    get_page_fetch_state,
    set_page_fetch_state,
    upsert_discovery,
    count_pages,
    count_discoveries,
    count_terms,
    count_postings,
    count_page_links,
)
from .url_normalizer import canonicalize_url


class IndexError(ValueError):
    """Raised when index() rejects its arguments."""


class Coordinator:
    def __init__(self, config: Config = DEFAULT_CONFIG) -> None:
        self.config = config
        self.db: sqlite3.Connection = open_db(config.db_path)
        self.frontier: Frontier = Frontier(maxsize=config.frontier_max_size)

    # ------------------------------------------------------------------
    # index
    # ------------------------------------------------------------------

    def index(self, origin: str, max_depth: int) -> CrawlJob:
        if not isinstance(max_depth, int) or max_depth < 0:
            raise IndexError(f"k must be a non-negative integer, got: {max_depth!r}")

        canonical = canonicalize_url(origin)
        if canonical is None:
            raise IndexError(f"unsupported or invalid URL: {origin!r}")

        job_id = uuid.uuid4().hex[:10]
        now = datetime.now(timezone.utc).isoformat()

        insert_crawl_job(
            self.db,
            job_id=job_id,
            origin_url=canonical,
            max_depth=max_depth,
            created_at=now,
        )

        page_id, _ = get_or_create_page(self.db, canonical)

        upsert_discovery(
            self.db,
            job_id=job_id,
            page_id=page_id,
            depth=0,
            parent_page_id=None,
            discovered_at=now,
        )

        fetch_state = get_page_fetch_state(self.db, page_id)
        if fetch_state == FetchState.UNFETCHED.value:
            item = FrontierItem(
                url=canonical,
                job_id=job_id,
                depth=0,
                page_id=page_id,
                parent_page_id=None,
            )
            if self.frontier.admit(item):
                set_page_fetch_state(self.db, page_id, FetchState.QUEUED.value)

        return CrawlJob(
            job_id=job_id,
            origin_url=canonical,
            max_depth=max_depth,
            status=JobStatus.PENDING,
            created_at=datetime.fromisoformat(now),
        )

    # ------------------------------------------------------------------
    # step — synchronous one-item pipeline
    # ------------------------------------------------------------------

    def step(self) -> StepResult:
        item = self.frontier.get(timeout=0.0)
        if item is None:
            return StepResult(processed=False)

        fetch_result = fetch_url(
            item.url,
            timeout=float(self.config.request_timeout),
            max_bytes=self.config.fetch_max_bytes,
            user_agent=self.config.user_agent,
        )

        parsed = None
        if fetch_result.outcome == FetchOutcome.HTML_SUCCESS and fetch_result.body:
            parsed = parse_html(fetch_result.body, base_url=fetch_result.final_url)

        children_admitted = persist_page(
            self.db,
            self.frontier,
            item=item,
            fetch_result=fetch_result,
            parsed=parsed,
        )

        self.frontier.task_done()

        return StepResult(
            processed=True,
            url=fetch_result.final_url,
            outcome=fetch_result.outcome.value,
            title=parsed.title if parsed else None,
            links_found=len(parsed.outgoing_urls) if parsed else 0,
            children_admitted=children_admitted,
            error=fetch_result.error,
        )

    # ------------------------------------------------------------------
    # search (stub — postings search comes in next patch)
    # ------------------------------------------------------------------

    def search(self, query: str, limit: int = 50) -> list[SearchRow]:
        return db_search(self.db, query, limit=limit)

    # ------------------------------------------------------------------
    # status / jobs
    # ------------------------------------------------------------------

    def status(self) -> dict:
        snap = self.frontier.snapshot()
        return {
            # frontier
            "frontier_size": snap.size,
            "frontier_capacity": snap.capacity,
            "backpressure": snap.backpressure,
            # db counts  (keys match bare table names + _total)
            "crawl_jobs_total": count_crawl_jobs(self.db),
            "pages_total": count_pages(self.db),
            "discoveries_total": count_discoveries(self.db),
            "page_links_total": count_page_links(self.db),
            "terms_total": count_terms(self.db),
            "postings_total": count_postings(self.db),
        }

    def jobs(self) -> list[sqlite3.Row]:
        return list_crawl_jobs(self.db)
