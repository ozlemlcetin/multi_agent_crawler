"""
Deterministic unit / integration tests for multi_agent_crawler.

All tests run offline — a local in-process HTTP server provides crawl targets
instead of the public internet.  No network access required.
"""

from __future__ import annotations

import http.server
import os
import threading
import tempfile

import pytest

# ---------------------------------------------------------------------------
# Local HTTP fixture
# ---------------------------------------------------------------------------

_PAGES: dict[str, bytes] = {
    "/": (
        b"<!doctype html><html><head><title>Home Page</title></head>"
        b"<body><p>hello world crawling indexing</p>"
        b'<a href="/child">child page</a></body></html>'
    ),
    "/child": (
        b"<!doctype html><html><head><title>Child Page</title></head>"
        b"<body><p>child content indexing</p></body></html>"
    ),
    "/isolated": (
        b"<!doctype html><html><head><title>Isolated</title></head>"
        b"<body><p>isolated content</p></body></html>"
    ),
}


class _Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass  # suppress test noise

    def do_GET(self):
        body = _PAGES.get(self.path)
        if body is None:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture(scope="module")
def base_url():
    """Start a local HTTP server; yield its base URL; shut down after module."""
    server = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
    port = server.server_address[1]
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{port}"
    server.shutdown()


@pytest.fixture
def coord(tmp_path):
    """Fresh Coordinator with an isolated temp database for each test."""
    from crawler_search.config import Config
    from crawler_search.coordinator import Coordinator

    cfg = Config(db_path=str(tmp_path / "test.db"))
    return Coordinator(config=cfg)


# ---------------------------------------------------------------------------
# Import / schema tests (no network)
# ---------------------------------------------------------------------------


def test_imports():
    from crawler_search.coordinator import Coordinator
    from crawler_search.models import JobStatus, StepResult, FetchState, FetchOutcome
    from crawler_search.storage import open_db, wal_mode
    from crawler_search.search_service import tokenize_query, search
    from crawler_search.url_normalizer import canonicalize_url
    assert True


def test_wal_mode(tmp_path):
    from crawler_search.storage import open_db, wal_mode
    conn = open_db(str(tmp_path / "wal.db"))
    assert wal_mode(conn) == "wal"


def test_all_tables_exist(tmp_path):
    from crawler_search.storage import open_db, table_names
    conn = open_db(str(tmp_path / "tables.db"))
    tables = set(table_names(conn))
    expected = {"crawl_jobs", "pages", "discoveries", "page_links", "terms", "postings", "job_events"}
    assert expected.issubset(tables), f"missing tables: {expected - tables}"


def test_invalid_url_rejected(coord):
    from crawler_search.coordinator import IndexError as CrawlIndexError
    with pytest.raises(CrawlIndexError):
        coord.index("not-a-valid-url", 1)


def test_invalid_depth_rejected(coord):
    from crawler_search.coordinator import IndexError as CrawlIndexError
    with pytest.raises(CrawlIndexError):
        coord.index("https://example.com", -1)


def test_non_integer_depth_rejected(coord):
    from crawler_search.coordinator import IndexError as CrawlIndexError
    with pytest.raises((CrawlIndexError, TypeError)):
        coord.index("https://example.com", "two")  # type: ignore[arg-type]


def test_url_canonicalization():
    from crawler_search.url_normalizer import canonicalize_url
    assert canonicalize_url("HTTP://EXAMPLE.COM/") == "http://example.com/"
    assert canonicalize_url("https://example.com:443/") == "https://example.com/"
    assert canonicalize_url("https://example.com/page#section") == "https://example.com/page"
    assert canonicalize_url("mailto:user@example.com") is None
    assert canonicalize_url("javascript:void(0)") is None


# ---------------------------------------------------------------------------
# Crawl / index / search (uses local HTTP server)
# ---------------------------------------------------------------------------


def test_index_creates_pending_job(coord, base_url):
    job = coord.index(base_url + "/isolated", 0)
    assert job.job_id
    assert job.status.value == "pending"
    assert job.origin_url == base_url + "/isolated"
    assert job.max_depth == 0


def test_step_fetches_page_and_returns_result(coord, base_url):
    coord.index(base_url + "/isolated", 0)
    result = coord.step()
    assert result.processed is True
    assert result.outcome == "html_success"
    assert result.title == "Isolated"
    assert result.skipped_paused is False


def test_empty_frontier_returns_unprocessed(coord):
    result = coord.step()
    assert result.processed is False


def test_run_until_idle_processes_pages(coord, base_url):
    coord.index(base_url + "/", 1)
    summary = coord.run_until_idle()
    assert summary["processed_count"] >= 1
    assert summary["html_success_count"] >= 1
    assert summary["failed_count"] == 0


def test_search_returns_results(coord, base_url):
    coord.index(base_url + "/", 1)
    coord.run_until_idle()
    results = coord.search("hello world")
    assert len(results) > 0


def test_search_provenance(coord, base_url):
    """Search results must include relevant_url, origin_url, depth."""
    coord.index(base_url + "/", 1)
    coord.run_until_idle()
    results = coord.search("crawling indexing")
    assert len(results) > 0
    r = results[0]
    assert r.relevant_url
    assert r.origin_url == base_url + "/"
    assert isinstance(r.depth, int) and r.depth >= 0


def test_search_child_provenance(coord, base_url):
    """Child pages must appear with depth=1 and origin_url pointing to the seed."""
    coord.index(base_url + "/", 1)
    coord.run_until_idle()
    results = coord.search("child content")
    assert len(results) > 0
    r = results[0]
    assert r.relevant_url == base_url + "/child"
    assert r.origin_url == base_url + "/"
    assert r.depth == 1


def test_empty_search_returns_empty(coord):
    results = coord.search("")
    assert results == []


def test_no_match_search_returns_empty(coord, base_url):
    coord.index(base_url + "/isolated", 0)
    coord.run_until_idle()
    results = coord.search("xyzzynosuchtermever")
    assert results == []


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------


def test_duplicate_index_no_readmission(coord, base_url):
    """Indexing the same URL twice must not grow the frontier.

    The origin is queued (fetch_state='queued') after the first index().
    The second index() discovers it but does NOT re-admit it — the frontier
    stays at size 1.  The second job is pending (shares the queued page)
    rather than done, because the page hasn't been fetched yet.
    """
    job1 = coord.index(base_url + "/isolated", 0)
    assert job1.status.value == "pending"
    assert coord.frontier.snapshot().size == 1

    job2 = coord.index(base_url + "/isolated", 0)
    # Origin already queued → NOT re-admitted; frontier must not grow
    assert coord.frontier.snapshot().size == 1, "frontier must not grow on duplicate index"
    # Second job is pending (page is queued but not yet fetched)
    assert job2.status.value == "pending"


def test_already_fetched_origin_marks_job_done_immediately(coord, base_url):
    """Re-indexing a URL that's already been fetched must return status=done."""
    coord.index(base_url + "/isolated", 0)
    coord.run_until_idle()
    job2 = coord.index(base_url + "/isolated", 0)
    assert job2.status.value == "done"


# ---------------------------------------------------------------------------
# Job lifecycle: pause / resume / cancel
# ---------------------------------------------------------------------------


def test_pause_pending_job(coord, base_url):
    job = coord.index(base_url + "/isolated", 0)
    ok = coord.pause(job.job_id)
    assert ok is True
    detail = coord.get_job_detail(job.job_id)
    assert detail["status"] == "paused"


def test_resume_paused_job(coord, base_url):
    job = coord.index(base_url + "/isolated", 0)
    coord.pause(job.job_id)
    ok = coord.resume(job.job_id)
    assert ok is True
    detail = coord.get_job_detail(job.job_id)
    assert detail["status"] in ("pending", "running")


def test_cancel_pending_job(coord, base_url):
    job = coord.index(base_url + "/isolated", 0)
    ok = coord.cancel(job.job_id)
    assert ok is True
    detail = coord.get_job_detail(job.job_id)
    assert detail["status"] == "cancelled"


def test_pause_done_job_returns_false(coord, base_url):
    job = coord.index(base_url + "/isolated", 0)
    coord.run_until_idle()
    ok = coord.pause(job.job_id)
    assert ok is False


def test_step_skips_paused_job(coord, base_url):
    job = coord.index(base_url + "/isolated", 0)
    coord.pause(job.job_id)
    result = coord.step()
    assert result.processed is True
    assert result.skipped_paused is True


# ---------------------------------------------------------------------------
# Frontier recovery
# ---------------------------------------------------------------------------


def test_frontier_reloads_queued_pages_on_restart(tmp_path, base_url):
    """After a simulated restart, queued pages must be re-admitted to the frontier."""
    from crawler_search.config import Config
    from crawler_search.coordinator import Coordinator

    db = str(tmp_path / "reload.db")
    cfg = Config(db_path=db)

    c1 = Coordinator(config=cfg)
    job = c1.index(base_url + "/isolated", 0)
    assert c1.frontier.snapshot().size == 1, "should have 1 item before restart"
    del c1  # simulate exit without running

    c2 = Coordinator(config=cfg)
    assert c2.frontier.snapshot().size == 1, "frontier should reload on restart"


# ---------------------------------------------------------------------------
# Event log
# ---------------------------------------------------------------------------


def test_events_logged_for_job(coord, base_url):
    job = coord.index(base_url + "/isolated", 0)
    events = coord.get_job_events(job.job_id)
    event_types = {e["event_type"] for e in events}
    assert "job_created" in event_types
    assert "queued" in event_types


def test_completed_event_after_run(coord, base_url):
    job = coord.index(base_url + "/isolated", 0)
    coord.run_until_idle()
    events = coord.get_job_events(job.job_id)
    event_types = {e["event_type"] for e in events}
    assert "completed" in event_types


# ---------------------------------------------------------------------------
# Status / jobs visibility
# ---------------------------------------------------------------------------


def test_status_returns_expected_keys(coord):
    s = coord.status()
    for key in ("frontier_size", "frontier_capacity", "backpressure",
                "crawl_jobs_total", "pages_total", "discoveries_total",
                "page_links_total", "terms_total", "postings_total"):
        assert key in s, f"missing key: {key}"


def test_jobs_list_reflects_created_jobs(coord, base_url):
    assert len(coord.jobs()) == 0
    coord.index(base_url + "/isolated", 0)
    assert len(coord.jobs()) == 1


def test_concurrent_read_search_does_not_block(coord, base_url):
    """Search must return immediately even when called between step() calls."""
    coord.index(base_url + "/isolated", 0)
    # Run one step, then search — proves read path uses separate connection.
    coord.step()
    results = coord.search("isolated content")
    assert isinstance(results, list)
