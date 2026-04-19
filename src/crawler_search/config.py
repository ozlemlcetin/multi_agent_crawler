from dataclasses import dataclass, field


@dataclass
class Config:
    max_workers: int = 4
    db_path: str = "crawler.db"
    user_agent: str = "crawler-search/0.1"
    request_timeout: int = 10
    frontier_max_size: int = 10_000
    fetch_max_bytes: int = 2 * 1024 * 1024  # 2 MB
    extra: dict = field(default_factory=dict)


DEFAULT_CONFIG = Config()
