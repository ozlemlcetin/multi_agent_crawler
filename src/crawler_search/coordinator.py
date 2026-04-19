"""Coordinator — write path serialised by a lock; reads use a separate connection."""

from __future__ import annotations

import sqlite3
import threading
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
    count_unfinished_pages_for_job,
    mark_job_running,
    set_job_status,
    set_job_paused,
    set_job_resumed,
    set_job_cancelled,
    get_crawl_job,
    get_queued_pages_for_job,
    get_queued_pages_for_active_jobs,
    get_job_progress,
    log_event,
    get_job_events,
    get_global_events,
    get_failed_pages,
    get_discovered_pages,
    get_active_jobs,
    get_jobs_count_by_status,
)
from .url_normalizer import canonicalize_url


class IndexError(ValueError):
    """Raised when index() rejects its arguments."""


class Coordinator:
    def __init__(self, config: Config = DEFAULT_CONFIG) -> None:
        self.config = config
        # Write connection — used exclusively by index() and step().
        self.db: sqlite3.Connection = open_db(config.db_path)
        # Read connection — used exclusively by search(), status(), jobs().
        # SQLite WAL: a separate connection reads committed snapshots without
        # ever waiting for the writer.
        self._read_db: sqlite3.Connection = open_db(config.db_path)
        # Serialises all writes to self.db so concurrent step()/index() calls
        # never interleave inside a transaction.  Lock is NOT held during
        # fetch_url() so reads can execute freely during network I/O.
        self._write_lock = threading.Lock()
        # Protects _is_running so only one run_until_idle() runs at a time.
        self._run_lock = threading.Lock()
        self._is_running = False
        self.frontier: Frontier = Frontier(maxsize=config.frontier_max_size)
        # Set of paused + cancelled job IDs — step() silently skips these items.
        self._skip_jobs: set[str] = set()
        self._load_skip_jobs()
        self._reload_frontier()

    # ------------------------------------------------------------------
    # Startup helpers
    # ------------------------------------------------------------------

    def _load_skip_jobs(self) -> None:
        rows = self.db.execute(
            "SELECT job_id FROM crawl_jobs WHERE status IN ('paused', 'cancelled')"
        ).fetchall()
        for row in rows:
            self._skip_jobs.add(row["job_id"])

    def _reload_frontier(self) -> None:
        """Re-admit queued pages for active (pending/running) jobs after restart."""
        rows = get_queued_pages_for_active_jobs(self.db)
        for row in rows:
            item = FrontierItem(
                url=row["canonical_url"],
                job_id=row["job_id"],
                depth=row["depth"],
                page_id=row["page_id"],
                parent_page_id=row["parent_page_id"],
            )
            self.frontier.admit(item)

    # ------------------------------------------------------------------
    # Run-guard helpers (used by web layer)
    # ------------------------------------------------------------------

    def try_start_run(self) -> bool:
        """Return True and mark running; False if already running."""
        with self._run_lock:
            if self._is_running:
                return False
            self._is_running = True
            return True

    def finish_run(self) -> None:
        with self._run_lock:
            self._is_running = False

    # ------------------------------------------------------------------
    # index
    # ------------------------------------------------------------------

    def index(self, origin: str, max_depth: int) -> CrawlJob:
        if not isinstance(max_depth, int) or max_depth < 0:
            raise IndexError(f"max_depth must be a non-negative integer, got: {max_depth!r}")

        canonical = canonicalize_url(origin)
        if canonical is None:
            raise IndexError(f"unsupported or invalid URL: {origin!r}")

        job_id = uuid.uuid4().hex[:10]
        now = datetime.now(timezone.utc).isoformat()

        with self._write_lock:
            insert_crawl_job(
                self.db,
                job_id=job_id,
                origin_url=canonical,
                max_depth=max_depth,
                created_at=now,
            )
            log_event(self.db, job_id, "job_created", url=canonical, ts=now)

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
                    log_event(self.db, job_id, "queued", url=canonical, ts=now)

            # If origin was already fetched/failed (or frontier was full), no work
            # will ever be admitted for this job — mark it done immediately so it
            # never stays stuck in pending.
            if count_unfinished_pages_for_job(self.db, job_id) == 0:
                now_fin = datetime.now(timezone.utc).isoformat()
                set_job_status(self.db, job_id, JobStatus.DONE.value, finished_at=now_fin)
                log_event(self.db, job_id, "completed", ts=now_fin)
                final_status = JobStatus.DONE
            else:
                final_status = JobStatus.PENDING

        return CrawlJob(
            job_id=job_id,
            origin_url=canonical,
            max_depth=max_depth,
            status=final_status,
            created_at=datetime.fromisoformat(now),
        )

    # ------------------------------------------------------------------
    # step — synchronous one-item pipeline
    # ------------------------------------------------------------------

    def step(self) -> StepResult:
        item = self.frontier.get(timeout=0.0)
        if item is None:
            return StepResult(processed=False)

        # Skip items belonging to paused or cancelled jobs.
        if item.job_id in self._skip_jobs:
            self.frontier.task_done()
            return StepResult(processed=True, skipped_paused=True, url=item.url)

        # Network I/O — no DB writes, lock NOT held, GIL released for the
        # duration of the fetch.  Read requests can execute freely here.
        fetch_result = fetch_url(
            item.url,
            timeout=float(self.config.request_timeout),
            max_bytes=self.config.fetch_max_bytes,
            user_agent=self.config.user_agent,
        )

        parsed = None
        if fetch_result.outcome == FetchOutcome.HTML_SUCCESS and fetch_result.body:
            parsed = parse_html(fetch_result.body, base_url=fetch_result.final_url)

        # DB write section — lock held only for these fast commit operations.
        with self._write_lock:
            now_start = datetime.now(timezone.utc).isoformat()
            mark_job_running(self.db, item.job_id, now_start)

            log_event(self.db, item.job_id, "fetching", url=item.url, ts=now_start)

            children_admitted = persist_page(
                self.db,
                self.frontier,
                item=item,
                fetch_result=fetch_result,
                parsed=parsed,
            )

            now_fetched = datetime.now(timezone.utc).isoformat()
            outcome_val = fetch_result.outcome.value
            log_event(
                self.db, item.job_id,
                "fetched" if fetch_result.outcome == FetchOutcome.HTML_SUCCESS else "failed",
                url=fetch_result.final_url,
                detail=f"outcome={outcome_val} children_admitted={children_admitted}",
                ts=now_fetched,
            )

            if count_unfinished_pages_for_job(self.db, item.job_id) == 0:
                now_fin = datetime.now(timezone.utc).isoformat()
                set_job_status(self.db, item.job_id, JobStatus.DONE.value, finished_at=now_fin)
                log_event(self.db, item.job_id, "completed", ts=now_fin)

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
    # run_until_idle — drain the frontier by calling step() repeatedly
    # ------------------------------------------------------------------

    def run_until_idle(self) -> dict:
        processed_count = 0
        html_success_count = 0
        non_html_count = 0
        failed_count = 0
        children_admitted_total = 0

        while True:
            result = self.step()
            if not result.processed:
                break
            if result.skipped_paused:
                continue  # don't count skipped items; keep draining
            processed_count += 1
            children_admitted_total += result.children_admitted
            outcome = result.outcome or ""
            if outcome == FetchOutcome.HTML_SUCCESS.value:
                html_success_count += 1
            elif outcome == FetchOutcome.NON_HTML.value:
                non_html_count += 1
            else:
                failed_count += 1

        return {
            "processed_count": processed_count,
            "html_success_count": html_success_count,
            "non_html_count": non_html_count,
            "failed_count": failed_count,
            "children_admitted_total": children_admitted_total,
        }

    # ------------------------------------------------------------------
    # pause / resume / cancel
    # ------------------------------------------------------------------

    def pause(self, job_id: str) -> bool:
        """Pause a pending or running job. Returns True if the job was paused."""
        with self._write_lock:
            row = get_crawl_job(self.db, job_id)
            if row is None or row["status"] not in ("pending", "running"):
                return False
            now = datetime.now(timezone.utc).isoformat()
            set_job_paused(self.db, job_id, now)
            log_event(self.db, job_id, "paused", ts=now)
        self._skip_jobs.add(job_id)
        return True

    def resume(self, job_id: str) -> bool:
        """Resume a paused job. Returns True if the job was resumed."""
        with self._write_lock:
            row = get_crawl_job(self.db, job_id)
            if row is None or row["status"] != "paused":
                return False
            self._skip_jobs.discard(job_id)
            # Re-admit all queued pages for this job back into the frontier.
            queued_rows = get_queued_pages_for_job(self.db, job_id)
            admitted = 0
            for qr in queued_rows:
                item = FrontierItem(
                    url=qr["canonical_url"],
                    job_id=job_id,
                    depth=qr["depth"],
                    page_id=qr["page_id"],
                    parent_page_id=qr["parent_page_id"],
                )
                if self.frontier.admit(item):
                    admitted += 1
            new_status = "running" if row["started_at"] else "pending"
            set_job_resumed(self.db, job_id, new_status)
            now = datetime.now(timezone.utc).isoformat()
            log_event(
                self.db, job_id, "resumed",
                detail=f"re_admitted={admitted}", ts=now,
            )
        return True

    def cancel(self, job_id: str) -> bool:
        """Cancel a pending, running, or paused job. Returns True if cancelled."""
        with self._write_lock:
            row = get_crawl_job(self.db, job_id)
            if row is None or row["status"] not in ("pending", "running", "paused"):
                return False
            now = datetime.now(timezone.utc).isoformat()
            set_job_cancelled(self.db, job_id, now)
            log_event(self.db, job_id, "cancelled", ts=now)
        self._skip_jobs.add(job_id)
        return True

    # ------------------------------------------------------------------
    # search — dedicated read connection, never waits for writer
    # ------------------------------------------------------------------

    def search(self, query: str, limit: int = 50) -> list[SearchRow]:
        return db_search(self._read_db, query, limit=limit)

    # ------------------------------------------------------------------
    # status / jobs — dedicated read connection
    # ------------------------------------------------------------------

    def status(self) -> dict:
        snap = self.frontier.snapshot()
        return {
            "frontier_size": snap.size,
            "frontier_capacity": snap.capacity,
            "backpressure": snap.backpressure,
            "crawl_jobs_total": count_crawl_jobs(self._read_db),
            "pages_total": count_pages(self._read_db),
            "discoveries_total": count_discoveries(self._read_db),
            "page_links_total": count_page_links(self._read_db),
            "terms_total": count_terms(self._read_db),
            "postings_total": count_postings(self._read_db),
        }

    def jobs(self) -> list[sqlite3.Row]:
        return list_crawl_jobs(self._read_db)

    # ------------------------------------------------------------------
    # job detail — read connection
    # ------------------------------------------------------------------

    def get_job_detail(self, job_id: str) -> dict | None:
        row = get_crawl_job(self._read_db, job_id)
        if row is None:
            return None
        progress = get_job_progress(self._read_db, job_id)
        return {
            "job_id":      row["job_id"],
            "origin_url":  row["origin_url"],
            "max_depth":   row["max_depth"],
            "status":      row["status"],
            "created_at":  row["created_at"],
            "started_at":  row["started_at"],
            "finished_at": row["finished_at"],
            "paused_at":   row["paused_at"],
            **progress,
        }

    def get_job_events(self, job_id: str, limit: int = 200) -> list[sqlite3.Row]:
        return get_job_events(self._read_db, job_id, limit=limit)

    def get_global_events(
        self,
        limit: int = 200,
        job_id: str | None = None,
        event_type: str | None = None,
        q: str | None = None,
    ) -> list[sqlite3.Row]:
        return get_global_events(self._read_db, limit=limit, job_id=job_id, event_type=event_type, q=q)

    def get_failed_pages(self, limit: int = 200) -> list[sqlite3.Row]:
        return get_failed_pages(self._read_db, limit=limit)

    def get_discovered_pages(
        self,
        job_id: str | None = None,
        fetch_state: str | None = None,
        depth: int | None = None,
        limit: int = 200,
    ) -> list[sqlite3.Row]:
        return get_discovered_pages(self._read_db, job_id=job_id, fetch_state=fetch_state, depth=depth, limit=limit)

    def retry_job(self, job_id: str) -> CrawlJob | None:
        """Create a new job from the same origin and depth as an existing job."""
        row = get_crawl_job(self._read_db, job_id)
        if row is None:
            return None
        return self.index(row["origin_url"], row["max_depth"])

    def get_dashboard_data(self) -> dict:
        snap = self.frontier.snapshot()
        status_counts = get_jobs_count_by_status(self._read_db)
        active_jobs = [dict(r) for r in get_active_jobs(self._read_db)]
        recent_events = [dict(r) for r in get_global_events(self._read_db, limit=10)]
        return {
            "frontier_size":     snap.size,
            "frontier_capacity": snap.capacity,
            "backpressure":      snap.backpressure,
            "pages_total":       count_pages(self._read_db),
            "jobs_total":        count_crawl_jobs(self._read_db),
            "discoveries_total": count_discoveries(self._read_db),
            "status_counts":     status_counts,
            "active_jobs":       active_jobs,
            "recent_events":     recent_events,
        }
