"""SQLite connection helper and schema initialisation."""

from __future__ import annotations

import sqlite3
from pathlib import Path

# ---------------------------------------------------------------------------
# DDL
# ---------------------------------------------------------------------------

_DDL = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS crawl_jobs (
    job_id      TEXT PRIMARY KEY,
    origin_url  TEXT NOT NULL,
    max_depth   INTEGER NOT NULL,
    status      TEXT NOT NULL DEFAULT 'pending',
    created_at  TEXT NOT NULL,
    started_at  TEXT,
    finished_at TEXT,
    paused_at   TEXT
);

CREATE TABLE IF NOT EXISTS pages (
    page_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    canonical_url TEXT NOT NULL UNIQUE,
    fetch_state  TEXT NOT NULL DEFAULT 'unfetched',
    http_status  INTEGER,
    content_type TEXT,
    title        TEXT,
    content_hash TEXT,
    fetched_at   TEXT
);

CREATE TABLE IF NOT EXISTS discoveries (
    job_id         TEXT NOT NULL REFERENCES crawl_jobs(job_id),
    page_id        INTEGER NOT NULL REFERENCES pages(page_id),
    depth          INTEGER NOT NULL,
    parent_page_id INTEGER REFERENCES pages(page_id),
    discovered_at  TEXT NOT NULL,
    PRIMARY KEY (job_id, page_id)
);

CREATE TABLE IF NOT EXISTS page_links (
    source_page_id INTEGER NOT NULL REFERENCES pages(page_id),
    target_page_id INTEGER NOT NULL REFERENCES pages(page_id),
    PRIMARY KEY (source_page_id, target_page_id)
);

CREATE TABLE IF NOT EXISTS terms (
    term_id INTEGER PRIMARY KEY AUTOINCREMENT,
    term    TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS postings (
    term_id        INTEGER NOT NULL REFERENCES terms(term_id),
    page_id        INTEGER NOT NULL REFERENCES pages(page_id),
    term_frequency INTEGER NOT NULL,
    PRIMARY KEY (term_id, page_id)
);
"""

_DDL_EXTRA = """
CREATE TABLE IF NOT EXISTS job_events (
    event_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id     TEXT NOT NULL REFERENCES crawl_jobs(job_id),
    event_type TEXT NOT NULL,
    url        TEXT,
    detail     TEXT,
    ts         TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_job_events_job_id ON job_events(job_id);
"""

_MIGRATIONS = [
    "ALTER TABLE crawl_jobs ADD COLUMN paused_at TEXT",
]

_EXPECTED_TABLES = frozenset(
    {"crawl_jobs", "pages", "discoveries", "page_links", "terms", "postings", "job_events"}
)

# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------


def _apply_migrations(conn: sqlite3.Connection) -> None:
    for sql in _MIGRATIONS:
        try:
            conn.execute(sql)
            conn.commit()
        except sqlite3.OperationalError:
            pass  # column already exists


def open_db(db_path: str | Path) -> sqlite3.Connection:
    """Open (or create) the SQLite database, apply pragmas, DDL, and migrations."""
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(_DDL)
    conn.commit()
    _apply_migrations(conn)
    conn.executescript(_DDL_EXTRA)
    conn.commit()
    return conn


# ---------------------------------------------------------------------------
# Inspection helpers
# ---------------------------------------------------------------------------


def schema_exists(conn: sqlite3.Connection) -> bool:
    """Return True when all expected tables are present."""
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    present = {row["name"] for row in rows}
    return _EXPECTED_TABLES.issubset(present)


def table_names(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    return [row["name"] for row in rows]


def wal_mode(conn: sqlite3.Connection) -> str:
    row = conn.execute("PRAGMA journal_mode").fetchone()
    return row[0]


# ---------------------------------------------------------------------------
# crawl_jobs helpers
# ---------------------------------------------------------------------------


def insert_crawl_job(
    conn: sqlite3.Connection,
    *,
    job_id: str,
    origin_url: str,
    max_depth: int,
    status: str = "pending",
    created_at: str,
) -> None:
    conn.execute(
        """
        INSERT INTO crawl_jobs (job_id, origin_url, max_depth, status, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (job_id, origin_url, max_depth, status, created_at),
    )
    conn.commit()


def list_crawl_jobs(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM crawl_jobs ORDER BY created_at DESC"
    ).fetchall()


def count_crawl_jobs(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM crawl_jobs").fetchone()[0]


def count_unfinished_pages_for_job(conn: sqlite3.Connection, job_id: str) -> int:
    """Count pages discovered for this job that are still unfetched or queued."""
    return conn.execute(
        """
        SELECT COUNT(*) FROM discoveries d
        JOIN pages p ON p.page_id = d.page_id
        WHERE d.job_id = ? AND p.fetch_state IN ('unfetched', 'queued')
        """,
        (job_id,),
    ).fetchone()[0]


def mark_job_running(conn: sqlite3.Connection, job_id: str, started_at: str) -> None:
    """Transition job from pending → running. No-op if already running or done."""
    conn.execute(
        """
        UPDATE crawl_jobs SET status = 'running', started_at = ?
        WHERE job_id = ? AND status = 'pending'
        """,
        (started_at, job_id),
    )
    conn.commit()


def set_job_status(
    conn: sqlite3.Connection,
    job_id: str,
    status: str,
    finished_at: str | None = None,
) -> None:
    conn.execute(
        "UPDATE crawl_jobs SET status = ?, finished_at = ? WHERE job_id = ?",
        (status, finished_at, job_id),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# pages helpers
# ---------------------------------------------------------------------------


def get_or_create_page(
    conn: sqlite3.Connection, canonical_url: str
) -> tuple[int, bool]:
    """Return (page_id, created). Insert with fetch_state='unfetched' if absent."""
    row = conn.execute(
        "SELECT page_id FROM pages WHERE canonical_url = ?", (canonical_url,)
    ).fetchone()
    if row:
        return row["page_id"], False
    cur = conn.execute(
        "INSERT INTO pages (canonical_url, fetch_state) VALUES (?, 'unfetched')",
        (canonical_url,),
    )
    conn.commit()
    return cur.lastrowid, True


def get_page_fetch_state(conn: sqlite3.Connection, page_id: int) -> str | None:
    row = conn.execute(
        "SELECT fetch_state FROM pages WHERE page_id = ?", (page_id,)
    ).fetchone()
    return row["fetch_state"] if row else None


def set_page_fetch_state(
    conn: sqlite3.Connection, page_id: int, state: str
) -> None:
    conn.execute(
        "UPDATE pages SET fetch_state = ? WHERE page_id = ?", (state, page_id)
    )
    conn.commit()


def count_pages(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM pages").fetchone()[0]


# ---------------------------------------------------------------------------
# discoveries helpers
# ---------------------------------------------------------------------------


def upsert_discovery(
    conn: sqlite3.Connection,
    *,
    job_id: str,
    page_id: int,
    depth: int,
    parent_page_id: int | None,
    discovered_at: str,
) -> None:
    """Insert discovery; on conflict keep the minimum depth."""
    conn.execute(
        """
        INSERT INTO discoveries (job_id, page_id, depth, parent_page_id, discovered_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(job_id, page_id) DO UPDATE SET
            depth = MIN(depth, excluded.depth)
        """,
        (job_id, page_id, depth, parent_page_id, discovered_at),
    )
    conn.commit()


def count_discoveries(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM discoveries").fetchone()[0]


# ---------------------------------------------------------------------------
# pages — write-back after fetch
# ---------------------------------------------------------------------------


def update_page_fetched(
    conn: sqlite3.Connection,
    *,
    page_id: int,
    fetch_state: str,
    http_status: int | None,
    content_type: str | None,
    title: str | None,
    content_hash: str | None,
    fetched_at: str,
) -> None:
    conn.execute(
        """
        UPDATE pages
           SET fetch_state  = ?,
               http_status  = ?,
               content_type = ?,
               title        = ?,
               content_hash = ?,
               fetched_at   = ?
         WHERE page_id = ?
        """,
        (fetch_state, http_status, content_type, title, content_hash, fetched_at, page_id),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# page_links
# ---------------------------------------------------------------------------


def replace_page_links(
    conn: sqlite3.Connection, source_page_id: int, target_page_ids: list[int]
) -> None:
    """Replace all outgoing links for source_page_id atomically."""
    conn.execute("DELETE FROM page_links WHERE source_page_id = ?", (source_page_id,))
    conn.executemany(
        "INSERT OR IGNORE INTO page_links (source_page_id, target_page_id) VALUES (?, ?)",
        [(source_page_id, t) for t in target_page_ids],
    )
    conn.commit()


def count_page_links(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM page_links").fetchone()[0]


# ---------------------------------------------------------------------------
# terms + postings
# ---------------------------------------------------------------------------


def get_or_create_term(conn: sqlite3.Connection, term: str) -> int:
    row = conn.execute("SELECT term_id FROM terms WHERE term = ?", (term,)).fetchone()
    if row:
        return row["term_id"]
    cur = conn.execute("INSERT INTO terms (term) VALUES (?)", (term,))
    return cur.lastrowid


def replace_postings(
    conn: sqlite3.Connection,
    page_id: int,
    term_freqs: dict[str, int],
) -> None:
    """Replace all postings for page_id atomically."""
    conn.execute("DELETE FROM postings WHERE page_id = ?", (page_id,))
    rows = []
    for term, freq in term_freqs.items():
        term_id = get_or_create_term(conn, term)
        rows.append((term_id, page_id, freq))
    conn.executemany(
        "INSERT OR REPLACE INTO postings (term_id, page_id, term_frequency) VALUES (?, ?, ?)",
        rows,
    )
    conn.commit()


def count_terms(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM terms").fetchone()[0]


def count_postings(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM postings").fetchone()[0]


# ---------------------------------------------------------------------------
# crawl_jobs — max_depth lookup needed by writer
# ---------------------------------------------------------------------------


def get_job_max_depth(conn: sqlite3.Connection, job_id: str) -> int | None:
    row = conn.execute(
        "SELECT max_depth FROM crawl_jobs WHERE job_id = ?", (job_id,)
    ).fetchone()
    return row["max_depth"] if row else None


def get_crawl_job(conn: sqlite3.Connection, job_id: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM crawl_jobs WHERE job_id = ?", (job_id,)
    ).fetchone()


def set_job_paused(conn: sqlite3.Connection, job_id: str, paused_at: str) -> None:
    conn.execute(
        """
        UPDATE crawl_jobs SET status = 'paused', paused_at = ?
        WHERE job_id = ? AND status IN ('pending', 'running')
        """,
        (paused_at, job_id),
    )
    conn.commit()


def set_job_resumed(conn: sqlite3.Connection, job_id: str, new_status: str) -> None:
    conn.execute(
        """
        UPDATE crawl_jobs SET status = ?, paused_at = NULL
        WHERE job_id = ? AND status = 'paused'
        """,
        (new_status, job_id),
    )
    conn.commit()


def set_job_cancelled(conn: sqlite3.Connection, job_id: str, finished_at: str) -> None:
    conn.execute(
        """
        UPDATE crawl_jobs SET status = 'cancelled', finished_at = ?
        WHERE job_id = ? AND status IN ('pending', 'running', 'paused')
        """,
        (finished_at, job_id),
    )
    conn.commit()


def get_queued_pages_for_job(
    conn: sqlite3.Connection, job_id: str
) -> list[sqlite3.Row]:
    """Return all queued (fetch_state='queued') pages discovered by this job."""
    return conn.execute(
        """
        SELECT p.page_id, p.canonical_url, d.depth, d.parent_page_id
          FROM discoveries d
          JOIN pages p ON p.page_id = d.page_id
         WHERE d.job_id = ? AND p.fetch_state = 'queued'
        """,
        (job_id,),
    ).fetchall()


def get_queued_pages_for_active_jobs(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Return queued pages for jobs that are pending or running (for frontier reload)."""
    return conn.execute(
        """
        SELECT p.page_id, p.canonical_url, d.depth, d.parent_page_id, d.job_id
          FROM discoveries d
          JOIN pages p ON p.page_id = d.page_id
          JOIN crawl_jobs j ON j.job_id = d.job_id
         WHERE j.status IN ('pending', 'running')
           AND p.fetch_state = 'queued'
        """,
    ).fetchall()


def get_job_progress(conn: sqlite3.Connection, job_id: str) -> dict:
    """Return counts for a single job: discovered, fetched, queued, unfetched, failed."""
    row = conn.execute(
        """
        SELECT
            COUNT(*) AS discovered,
            SUM(CASE WHEN p.fetch_state = 'fetched'   THEN 1 ELSE 0 END) AS fetched,
            SUM(CASE WHEN p.fetch_state = 'queued'    THEN 1 ELSE 0 END) AS queued,
            SUM(CASE WHEN p.fetch_state = 'unfetched' THEN 1 ELSE 0 END) AS unfetched,
            SUM(CASE WHEN p.fetch_state = 'failed'    THEN 1 ELSE 0 END) AS failed
          FROM discoveries d
          JOIN pages p ON p.page_id = d.page_id
         WHERE d.job_id = ?
        """,
        (job_id,),
    ).fetchone()
    return {
        "discovered": row["discovered"] or 0,
        "fetched":    row["fetched"]    or 0,
        "queued":     row["queued"]     or 0,
        "unfetched":  row["unfetched"]  or 0,
        "failed":     row["failed"]     or 0,
    }


# ---------------------------------------------------------------------------
# job_events helpers
# ---------------------------------------------------------------------------


def log_event(
    conn: sqlite3.Connection,
    job_id: str,
    event_type: str,
    *,
    url: str | None = None,
    detail: str | None = None,
    ts: str | None = None,
) -> None:
    from datetime import datetime, timezone
    if ts is None:
        ts = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO job_events (job_id, event_type, url, detail, ts) VALUES (?, ?, ?, ?, ?)",
        (job_id, event_type, url, detail, ts),
    )
    conn.commit()


def get_job_events(
    conn: sqlite3.Connection, job_id: str, limit: int = 200
) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM job_events WHERE job_id = ? ORDER BY event_id DESC LIMIT ?",
        (job_id, limit),
    ).fetchall()


def get_global_events(
    conn: sqlite3.Connection,
    limit: int = 200,
    job_id: str | None = None,
    event_type: str | None = None,
    q: str | None = None,
) -> list[sqlite3.Row]:
    conditions: list[str] = []
    params: list = []
    if job_id:
        conditions.append("e.job_id = ?")
        params.append(job_id)
    if event_type:
        conditions.append("e.event_type = ?")
        params.append(event_type)
    if q:
        conditions.append("(e.url LIKE ? OR e.detail LIKE ?)")
        params.extend([f"%{q}%", f"%{q}%"])
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    params.append(limit)
    return conn.execute(
        f"""
        SELECT e.*, j.origin_url
          FROM job_events e
          JOIN crawl_jobs j ON j.job_id = e.job_id
         {where}
         ORDER BY e.event_id DESC LIMIT ?
        """,
        params,
    ).fetchall()


def get_failed_pages(conn: sqlite3.Connection, limit: int = 200) -> list[sqlite3.Row]:
    """Return pages with fetch_state='failed', joined to job info (one row per page)."""
    return conn.execute(
        """
        SELECT p.canonical_url, p.http_status, p.content_type, p.fetched_at,
               d.job_id, d.depth, j.origin_url,
               e.detail AS error_detail, e.ts AS error_ts
          FROM pages p
          JOIN (
              SELECT page_id, MIN(job_id) AS job_id, MIN(depth) AS depth
                FROM discoveries GROUP BY page_id
          ) d ON d.page_id = p.page_id
          JOIN crawl_jobs j ON j.job_id = d.job_id
          LEFT JOIN (
              SELECT url, detail, ts, ROW_NUMBER() OVER (PARTITION BY url ORDER BY event_id DESC) AS rn
                FROM job_events WHERE event_type = 'failed'
          ) e ON e.url = p.canonical_url AND e.rn = 1
         WHERE p.fetch_state = 'failed'
         ORDER BY p.fetched_at DESC NULLS LAST
         LIMIT ?
        """,
        (limit,),
    ).fetchall()


def get_discovered_pages(
    conn: sqlite3.Connection,
    job_id: str | None = None,
    fetch_state: str | None = None,
    depth: int | None = None,
    limit: int = 200,
) -> list[sqlite3.Row]:
    conditions: list[str] = []
    params: list = []
    if job_id:
        conditions.append("d.job_id = ?")
        params.append(job_id)
    if fetch_state:
        conditions.append("p.fetch_state = ?")
        params.append(fetch_state)
    if depth is not None:
        conditions.append("d.depth = ?")
        params.append(depth)
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    params.append(limit)
    return conn.execute(
        f"""
        SELECT p.canonical_url, p.fetch_state, p.title, p.http_status, p.fetched_at,
               d.job_id, d.depth, d.discovered_at,
               j.origin_url,
               pp.canonical_url AS parent_url
          FROM discoveries d
          JOIN pages p   ON p.page_id  = d.page_id
          JOIN crawl_jobs j ON j.job_id = d.job_id
          LEFT JOIN pages pp ON pp.page_id = d.parent_page_id
         {where}
         ORDER BY d.discovered_at DESC
         LIMIT ?
        """,
        params,
    ).fetchall()


def get_active_jobs(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM crawl_jobs WHERE status IN ('pending','running','paused') ORDER BY created_at DESC"
    ).fetchall()


def get_jobs_count_by_status(conn: sqlite3.Connection) -> dict[str, int]:
    rows = conn.execute(
        "SELECT status, COUNT(*) AS cnt FROM crawl_jobs GROUP BY status"
    ).fetchall()
    return {r["status"]: r["cnt"] for r in rows}
