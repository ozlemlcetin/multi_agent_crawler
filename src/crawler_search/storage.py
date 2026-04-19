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
    finished_at TEXT
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

_EXPECTED_TABLES = frozenset(
    {"crawl_jobs", "pages", "discoveries", "page_links", "terms", "postings"}
)

# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------


def open_db(db_path: str | Path) -> sqlite3.Connection:
    """Open (or create) the SQLite database, apply pragmas and DDL."""
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(_DDL)
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
