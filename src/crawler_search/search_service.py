"""DB-backed search service — reads committed SQLite state only."""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass

_TOKEN_RE = re.compile(r"[a-z]{2,}", re.ASCII)


@dataclass(frozen=True)
class SearchRow:
    relevant_url: str
    origin_url: str
    depth: int
    matched_terms: int
    score: int      # summed term frequency across matched terms


def tokenize_query(query: str) -> list[str]:
    """Normalize query with the same rules the parser uses for indexing."""
    return _TOKEN_RE.findall(query.lower())


def search(conn: sqlite3.Connection, query: str, limit: int = 50) -> list[SearchRow]:
    """Return ranked SearchRow list for *query* using committed DB state."""
    terms = tokenize_query(query)
    if not terms:
        return []

    # Build a parameterized IN clause.
    placeholders = ",".join("?" * len(terms))

    # For each page that matches at least one query term, compute:
    #   matched_terms = number of distinct query terms that appear in the page
    #   score         = sum of term frequencies across those terms
    # Then join with discoveries and crawl_jobs to get origin_url / depth.
    # A page may appear in multiple jobs; return all (job, page) pairs.
    sql = f"""
        SELECT
            p.canonical_url   AS relevant_url,
            cj.origin_url     AS origin_url,
            d.depth           AS depth,
            COUNT(DISTINCT t.term) AS matched_terms,
            SUM(po.term_frequency) AS score
        FROM postings  po
        JOIN terms     t   ON t.term_id  = po.term_id
        JOIN pages     p   ON p.page_id  = po.page_id
        JOIN discoveries d ON d.page_id  = po.page_id
        JOIN crawl_jobs cj ON cj.job_id  = d.job_id
        WHERE t.term IN ({placeholders})
          AND p.fetch_state = 'fetched'
        GROUP BY p.page_id, cj.job_id
        ORDER BY matched_terms DESC, score DESC
        LIMIT ?
    """

    rows = conn.execute(sql, (*terms, limit)).fetchall()
    return [
        SearchRow(
            relevant_url=r["relevant_url"],
            origin_url=r["origin_url"],
            depth=r["depth"],
            matched_terms=r["matched_terms"],
            score=r["score"],
        )
        for r in rows
    ]
