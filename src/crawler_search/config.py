from __future__ import annotations

import os
from dataclasses import dataclass, field


def _default_db_path() -> str:
    """Return the DB path, respecting CRAWLER_DB_PATH env var.

    On Vercel (or any read-only filesystem), set CRAWLER_DB_PATH=/tmp/crawler.db
    so the database is created in the writable /tmp directory.
    """
    return os.environ.get("CRAWLER_DB_PATH", "crawler.db")


@dataclass
class Config:
    max_workers: int = 4
    db_path: str = field(default_factory=_default_db_path)
    user_agent: str = "crawler-search/0.1"
    request_timeout: int = 10
    frontier_max_size: int = 10_000
    fetch_max_bytes: int = 2 * 1024 * 1024  # 2 MB
    extra: dict = field(default_factory=dict)


DEFAULT_CONFIG = Config()
