# Product Requirements Document — multi_agent_crawler

## Summary

A local, single-process Python web crawler and keyword-based search system.
Users submit crawl jobs via a CLI shell or a local web UI, process pages with `step`
(one at a time) or `run` (full frontier drain), and query indexed content from either interface.
All state is persisted in a local SQLite database.

---

## Product Goal

Build a working localhost crawler and search tool that demonstrates:
- controlled web crawling from a user-supplied origin URL
- persistent page indexing into a structured local database
- keyword-based search over indexed content with provenance metadata
- clear system observability through CLI commands

The project is a course assignment deliverable. The runtime system is a
plain Python application. The multi-agent requirement for the assignment is
fulfilled through the development workflow, not through runtime AI components.

---

## Problem Statement

A user wants to crawl a website up to a configurable depth, store page content
and link structure locally, and later search the indexed content.

Existing tools (scrapy, whoosh, elasticsearch) are either too heavy, require
external services, or are not suitable for a standalone course assignment.
This project delivers a minimal, self-contained, stdlib-only implementation
that covers the full pipeline from URL submission to keyword search.

---

## Assignment-Aligned Core Requirements

1. Accept a seed URL and a maximum crawl depth from the user.
2. Crawl pages reachable from the seed URL within the depth limit.
3. Store crawled page content and metadata in a local database.
4. Support keyword search over the indexed content.
5. Return search results that include the matched URL, the origin of the crawl
   that discovered it, and the depth at which it was found.
6. Operate entirely on localhost with no external service dependencies.
7. Use a multi-agent workflow for development (not for runtime execution).

---

## User-Facing Interface Expectations

The system exposes two interfaces:

**CLI shell:**
```
crawler-search run
```

**Local web UI (optional, requires `flask`):**
```
PORT=5001 crawler-search-web
```

The CLI shell accepts:

| Command | Purpose |
|---|---|
| `index <url> <depth>` | Submit a crawl job for `<url>` up to `<depth>` hops |
| `step` | Process one queued page synchronously |
| `run` | Drain the full frontier — process all queued pages until idle |
| `search <query>` | Search indexed pages and print result rows |
| `jobs` | List all submitted crawl jobs |
| `status` | Show frontier state and database counts |
| `help` | Print command reference |
| `quit` | Exit the shell |

The web UI exposes the same operations via a browser at `http://localhost:<PORT>`
with a REST API (`POST /api/index`, `POST /api/step`, `POST /api/run`,
`GET /api/search`, `GET /api/jobs`, `GET /api/status`).

---

## Functional Requirements

### Indexing

- The user provides a canonical HTTP/HTTPS seed URL and a non-negative integer depth.
- The system creates a crawl job record and admits the seed URL to the frontier queue.
- `step` pops one URL, fetches it, parses it, and persists results.
- Outgoing links discovered during parsing are canonicalized, resolved, and admitted
  as children if their depth does not exceed the job's `max_depth`.
- Persisted data per page: canonical URL, fetch state, HTTP status, content type,
  title, content hash, fetched timestamp, outgoing links, extracted terms and term frequencies.

### Search

- The user submits a free-text query.
- Query terms are tokenized with the same rules used at index time (lowercase, `[a-z]{2,}`).
- The system matches pages containing at least one query term.
- Results are ranked by number of matched distinct terms (descending), then by summed
  term frequency (descending).
- Each result row contains: `relevant_url`, `origin_url`, `depth`.
- Only pages with `fetch_state = 'fetched'` appear in results.
- Search reads committed database state only.

### State Visibility

- `status` reports frontier size, frontier capacity, backpressure flag, and row counts
  for all six database tables.
- `jobs` shows all submitted jobs with id, status, max depth, creation time, and origin URL.
- `step` reports the outcome of each processed page (URL, HTTP outcome, title, link count,
  children admitted).

### Provenance

- Every discovered page is linked to the crawl job that discovered it via the `discoveries`
  table, recording the depth and parent page at which it was found.
- Search results surface `origin_url` and `depth` alongside `relevant_url` so the user
  knows how and from where each result was reached.

### Deduplication

- URLs are canonicalized before any DB write or frontier admission.
- A page that is already in `queued` or `fetched` state is never re-admitted to the frontier,
  regardless of how many jobs reference it.
- Duplicate outgoing links within a parsed page are discarded before admission.
- Discovery records use min-depth semantics: if a page is re-discovered at a shallower depth
  in the same job, the existing record is updated.

### Backpressure

- The frontier queue has a configurable maximum size (default: 10,000).
- When occupancy reaches 80%, the backpressure flag is set to `True`.
- `status` exposes the backpressure state.
- Backpressure is a visibility signal; the system does not implement automatic throttling
  or a crawl politeness framework.

---

## System Constraints

- **Language:** Python 3.11 or later.
- **Dependencies:** Python stdlib only. No third-party packages.
- **Database:** SQLite with WAL journal mode and foreign key enforcement.
- **Persistence:** Local file `crawler.db` in the working directory.
- **Concurrency:** Single process. The CLI is fully synchronous. The web server runs with `threaded=True` (Flask thread-per-request) so read endpoints (search, status, jobs) are served concurrently with an active `/api/run`. Indexing itself remains single-threaded — one page is fetched at a time.
- **Interface:** CLI shell (stdlib-only). Optional local web UI via Flask (`pip install -e ".[web]"`).
- **Networking:** `urllib` only. HTTP and HTTPS schemes only.
- **Platform:** localhost. No distributed components.

---

## Technical Approach / Architecture

```
CLI shell  →  Coordinator  →  Frontier (bounded queue)
                          →  fetch_url (urllib)
                          →  parse_html (HTMLParser)
                          →  persist_page (index_writer)
                          →  search (search_service + SQLite)
                          →  SQLite DB (storage + WAL)
```

- The `Coordinator` is the single orchestration point. It owns the frontier and two SQLite connections: a write connection (`self.db`) used exclusively by `index()` and `step()`, and a read connection (`self._read_db`) used exclusively by `search()`, `status()`, and `jobs()`.
- All writes to `self.db` are serialised by a `threading.Lock`. The lock is released during the network-I/O phase of `step()`, so read requests can execute freely while a fetch is in flight.
- The frontier is an in-memory `queue.Queue`; it is not persisted across sessions.
- URL normalization (`url_normalizer`) is applied at every boundary: admission, parsing, and child discovery.

---

## Data Model Overview

| Table | Key columns | Purpose |
|---|---|---|
| `crawl_jobs` | `job_id`, `origin_url`, `max_depth`, `status`, `created_at` | One row per `index` call |
| `pages` | `page_id`, `canonical_url`, `fetch_state`, `http_status`, `title`, `content_hash`, `fetched_at` | One row per unique canonical URL |
| `discoveries` | `(job_id, page_id)` PK, `depth`, `parent_page_id`, `discovered_at` | Provenance: which job found which page at what depth |
| `page_links` | `(source_page_id, target_page_id)` PK | Outgoing link graph |
| `terms` | `term_id`, `term` | Deduplicated vocabulary |
| `postings` | `(term_id, page_id)` PK, `term_frequency` | Inverted index |

---

## Relevance / Search Behavior

- Tokenization: lowercase ASCII words of 2+ alphabetic characters (`[a-z]{2,}`).
- Matching: OR across all query terms; a page matches if it contains at least one.
- Ranking: primary sort by count of distinct matched terms; secondary sort by summed
  term frequency across matched terms.
- No stemming, stop-word removal, TF-IDF, or PageRank in MVP.

---

## Search While Indexing

The web interface supports true concurrent search while indexing is active. When
`POST /api/run` is processing pages, `GET /api/search`, `GET /api/status`, and
`GET /api/jobs` are served on separate threads via Flask's `threaded=True` mode and
return immediately using a dedicated read-only SQLite connection. Results reflect all
pages committed to the database up to the moment the search query executes.

The mechanism: `step()` holds the write lock only during the fast DB-commit phase; the
lock is released for the entire network-I/O portion (the majority of each step's
wall-clock time). The read connection uses SQLite WAL mode, which guarantees readers
never wait for an active writer on a separate connection.

The CLI remains synchronous — `run` and `step` block until complete, but the user can
call `search` between any two steps to see incrementally indexed results.

---

## MVP Boundaries / Non-Goals

The following are explicitly out of scope for MVP:

- Multi-worker parallel crawling (concurrent fetches; current threading is request-handling only, not parallel indexing)
- Frontier persistence and recovery across sessions
- Recrawl of already-fetched pages
- `robots.txt` compliance or per-host rate limiting
- TF-IDF, BM25, PageRank, or semantic ranking
- Distributed or multi-machine execution
- Runtime LLM agents or AI-assisted crawling decisions
- Authentication-gated or JavaScript-rendered pages
- Any scheme other than `http` and `https`

---

## Acceptance Criteria

1. `pip install -e .` completes successfully and the project requires no
   project-specific third-party runtime dependencies.
2. `crawler-search run` opens the interactive shell.
3. `index https://example.com 1` creates a crawl job and admits the origin URL to the frontier.
4. `step` fetches the queued URL, parses HTML, persists page metadata, terms, postings,
   page links, and child discoveries at depth 1.
5. `search example` returns at least the origin page with correct `relevant_url`,
   `origin_url`, and `depth` fields.
6. Running `index` on the same origin twice creates two job rows but only one page row
   and does not re-admit an already-queued URL to the frontier.
7. `jobs` shows all submitted jobs in tabular format.
8. `status` shows correct frontier size and database row counts after each operation.
9. An invalid URL passed to `index` is rejected with a clear error message.
10. A negative or non-integer depth passed to `index` is rejected with a clear error message.
11. `search` on a term with no indexed matches returns `(no results)` cleanly.
12. WAL mode is active on the SQLite database.
13. All six schema tables exist after first run.

---

## Example Success Scenarios

### Scenario 1 — Basic crawl and search

```
>>> index https://example.com 1
job created  id=abc123  depth=1  url=https://example.com/

>>> step
[html_success]  https://example.com/
title           'Example Domain'
links found     1
children admitted  1

>>> search domain
  relevant_url              origin_url              depth
  https://example.com/      https://example.com/    0

>>> status
  frontier size      1
  frontier capacity  10000
  backpressure       False
  crawl jobs         1
  pages              2
  discoveries        2
  page links         1
  terms              16
  postings           16
```

### Scenario 2 — Duplicate origin suppression

```
>>> index https://example.com 1
job created  id=aaa  ...

>>> index https://example.com 2
job created  id=bbb  ...   ← new job, no duplicate frontier admission

>>> status
  crawl jobs   2
  pages        1           ← one shared page row
  frontier size  1         ← admitted once
```

### Scenario 3 — Invalid input rejection

```
>>> index mailto:user@example.com 1
error: unsupported or invalid URL: 'mailto:user@example.com'

>>> index https://example.com -1
error: k must be a non-negative integer, got: -1
```

---

## Future Extensions

The following are candidates for post-MVP patches, in rough priority order:

1. **Background worker threads** — run `step` in a thread pool; the write path is already
   structured for this.
2. **Frontier recovery** — reload `queued` pages from the DB into the in-memory frontier on
   startup, enabling session continuity.
3. **Recrawl support** — allow re-fetching pages past a configurable staleness threshold.
4. **Crawl politeness** — `robots.txt` parsing and per-host request pacing.
5. **Improved ranking** — TF-IDF normalization or BM25 over the existing postings table.
6. **Configurable storage path** — pass `--db` flag to `crawler-search run`.
7. **Export** — dump indexed pages or search results to JSON or CSV.
8. **JavaScript rendering** — integrate a headless browser for JS-heavy pages.
