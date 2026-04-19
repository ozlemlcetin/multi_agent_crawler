from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class JobStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


class FetchState(Enum):
    UNFETCHED = "unfetched"
    QUEUED = "queued"
    FETCHED = "fetched"
    FAILED = "failed"


@dataclass
class CrawlJob:
    job_id: str
    origin_url: str
    max_depth: int
    status: JobStatus = JobStatus.PENDING
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    started_at: datetime | None = None
    finished_at: datetime | None = None


@dataclass
class FrontierItem:
    url: str
    job_id: str
    depth: int
    page_id: int
    parent_page_id: int | None = None


class FetchOutcome(Enum):
    HTML_SUCCESS = "html_success"
    NON_HTML = "non_html"
    HTTP_ERROR = "http_error"
    NETWORK_ERROR = "network_error"
    INVALID_INPUT = "invalid_input"


@dataclass
class FetchResult:
    requested_url: str
    final_url: str
    outcome: FetchOutcome
    http_status: int | None = None
    content_type: str | None = None
    body: str | None = None       # decoded text, HTML responses only
    error: str | None = None


@dataclass
class ParsedResult:
    title: str | None
    visible_text: str
    tokens: list[str]
    outgoing_urls: list[str]


@dataclass
class StepResult:
    """Summary returned by Coordinator.step()."""
    processed: bool           # False when frontier was empty
    url: str | None = None
    outcome: str | None = None
    title: str | None = None
    links_found: int = 0
    children_admitted: int = 0
    error: str | None = None
    skipped_paused: bool = False


@dataclass
class SearchResult:
    url: str
    title: str
    snippet: str
    score: float
