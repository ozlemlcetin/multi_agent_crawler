# multi_agent_crawler

A local Python web crawler and search system built as a course project.
The runtime is a plain single-process Python application with a CLI and an optional local web UI.
The "multi-agent" aspect refers to the **development workflow** only — not to the runtime system.

---

## Overview

`multi_agent_crawler` crawls HTTP/HTTPS websites, indexes page content into a local SQLite
database, and lets you search indexed pages from an interactive CLI shell or a multi-page
local web console. Everything runs on localhost — no external services required.

---

## Core Features

- **Interactive CLI shell** — `index`, `step`, `run`, `search`, `jobs`, `status`, `pause`, `resume`, `cancel`, `quit`
- **Multi-page local web UI** — Flask-based browser console with dedicated pages for Dashboard, Jobs, Logs, Errors, Pages, Search, and Status
- **Job lifecycle controls** — pause, resume, and cancel active crawl jobs; job status tracked as `pending → running → done / paused / cancelled / failed`
- **Persistent event log** — all job lifecycle events (`job_created`, `queued`, `fetching`, `fetched`, `failed`, `completed`, `paused`, `resumed`, `cancelled`) stored per job
- **Frontier recovery on restart** — pages in `queued` state are automatically re-admitted to the frontier when the application restarts, enabling session continuity
- **URL canonicalization** — scheme/host lowercasing, default-port stripping, fragment removal, relative-URL resolution
- **Synchronous page fetcher** — stdlib `urllib`, redirect following, charset-aware decoding, configurable byte cap
- **HTML parser** — title extraction, visible-text collection, link extraction, script/style suppression
- **Bounded frontier queue** — in-memory `queue.Queue` with configurable max size and backpressure flag
- **SQLite persistence** — WAL mode, 7-table schema; write path serialised by a threading lock, reads served from a dedicated second connection
- **Term-frequency search** — query tokenized consistently with indexing; results ranked by matched-term count then summed TF
- **Child admission deduplication** — a URL already queued or fetched globally is never re-enqueued

---

## Architecture Summary

```
CLI shell (cli.py)  ──┐
Web UI    (web.py)  ──┴── Coordinator (coordinator.py)
                                ├── Frontier  — bounded in-memory queue  (frontier.py)
                                ├── fetch_url — stdlib HTTP               (fetcher.py)
                                ├── parse_html — stdlib HTMLParser        (parser.py)
                                ├── persist_page — write path             (index_writer.py)
                                ├── search — DB read path                 (search_service.py)
                                └── SQLite DB — WAL, 7 tables             (storage.py)
```

Core modules are stdlib-only. The optional web UI requires `flask` (`pip install -e ".[web]"`).
The CLI processes pages synchronously (`step` and `run` block until complete).
The web server runs with `threaded=True` so search, status, and jobs requests are served
concurrently while `/api/run` is indexing in its own thread.

---

## Installation

Requires Python 3.11 or later.

```bash
pip install -e .
```

No third-party packages are installed for the core CLI. To also install the optional web UI:

```bash
pip install -e ".[web]"
```

---

## Running

**CLI (interactive shell):**
```bash
crawler-search run
# or
python -m crawler_search.cli run
```

**Web UI (local browser):**
```bash
PORT=5001 crawler-search-web
# then open http://localhost:5001
```

---

## CLI Commands

| Command | Description |
|---|---|
| `index <url> <depth>` | Create a crawl job for `<url>`, exploring up to `<depth>` hops from the origin |
| `step` | Pop one URL from the frontier, fetch it, parse it, persist results, admit children |
| `run` | Drain the full frontier — repeatedly calls `step` until no work remains |
| `pause <job_id>` | Pause a pending or running job (frontier items for that job are skipped) |
| `resume <job_id>` | Resume a paused job (re-admits its queued pages to the frontier) |
| `cancel <job_id>` | Cancel a pending, running, or paused job permanently |
| `search <query>` | Search indexed pages; terms are OR-matched, results show `(relevant_url, origin_url, depth)` |
| `jobs` | List all crawl jobs with id, status, depth, creation time, and origin URL |
| `status` | Show frontier size/capacity/backpressure and DB row counts |
| `help` | Print command reference |
| `quit` / `exit` / `q` | Exit the shell |

---

## Web UI Pages

The web UI is a multi-page local crawler console accessible at `http://localhost:<PORT>`.

| Page | Route | Description |
|---|---|---|
| Dashboard | `/dashboard` | System stats, active jobs, recent events, quick actions |
| Jobs | `/jobs` | Full job list with status filters, inline controls |
| Job Detail | `/jobs/<job_id>` | Per-job progress, event log, discovered pages, failures tabs |
| Logs | `/logs` | Global event log across all jobs, filterable |
| Errors | `/errors` | Failed pages with HTTP status breakdown |
| Pages | `/pages` | All discovered URLs with fetch-state and depth filters |
| Search | `/search` | Full-text search with results grouped by origin |
| Status | `/status` | Frontier metrics, DB counts, crawl controls |

---

## Example Demo Flow

```bash
crawler-search run
```

```
>>> index https://example.com 1
  job created  id=abc123  depth=1  url=https://example.com/

>>> run
  processed                 2
  html success              2
  non-html                  0
  failed                    0
  children admitted         1

>>> search example
  relevant_url                                      origin_url                            depth
  ────────────────────────────────────────────────  ────────────────────────────────────  ─────
  https://example.com/                              https://example.com/                  0

>>> quit
```

---

## Data / Storage

SQLite database file: `crawler.db` (created in the working directory on first run).
WAL journal mode is enabled. Foreign keys are enforced.

| Table | Purpose |
|---|---|
| `crawl_jobs` | One row per `index` call; tracks origin URL, max depth, status, timestamps |
| `pages` | One row per canonical URL; tracks fetch state, HTTP status, title, content hash |
| `discoveries` | Maps `(job_id, page_id)` to depth and parent; min-depth wins on conflict |
| `page_links` | Outgoing links extracted from each fetched HTML page |
| `terms` | Deduplicated vocabulary across all indexed pages |
| `postings` | `(term_id, page_id, term_frequency)` — the inverted index |
| `job_events` | Per-job event log; one row per lifecycle event |

---

## Known Limitations / MVP Boundaries

- **CLI is synchronous** — `step` and `run` block in the terminal; pages are processed one at a time. The web server handles search/status concurrently via Flask threading, but indexing itself is still single-threaded.
- **No recrawl support** — already-fetched pages are not re-fetched in a new session.
- **No TF-IDF or PageRank** — search ranking uses raw term frequency and match count only.
- **No crawl politeness framework** — no `robots.txt` handling or per-host rate pacing is implemented.
- **HTTP/HTTPS only** — `mailto:`, `ftp:`, `javascript:`, and other schemes are discarded.
- **Single process** — `max_workers` in config is reserved for future parallel crawl workers; fetching is currently single-threaded.
- **Web UI is local/dev only** — intended for localhost use only.

---

## Tests

```bash
python -m pytest tests/test_core.py -v
```

29 deterministic unit and integration tests, all running offline using a local in-process
HTTP server. No internet connection required. Tests cover: imports, WAL mode, schema,
URL canonicalization, indexing, search, provenance, deduplication, job lifecycle
(pause/resume/cancel), frontier recovery on restart, event logging, and status/jobs visibility.

`tests/test_concurrent.py` is a standalone demo script (not a pytest test) that proves
concurrent search/status during `/api/run`. Run it directly with `python tests/test_concurrent.py`.

---

## Repository Structure

```
multi_agent_crawler/
├── pyproject.toml          package metadata and entry points
└── src/
    └── crawler_search/
        ├── __init__.py
        ├── cli.py           interactive shell and argparse entry point
        ├── web.py           Flask web UI, REST API, and multi-page routes
        ├── templates/
        │   ├── _base.html   shared layout with navigation
        │   ├── dashboard.html
        │   ├── jobs.html
        │   ├── job_detail.html
        │   ├── logs.html
        │   ├── errors.html
        │   ├── pages.html
        │   ├── search.html
        │   └── status.html
        ├── config.py        Config dataclass
        ├── coordinator.py   orchestrates index / step / search / status / pause / resume / cancel
        ├── fetcher.py       synchronous HTTP fetch
        ├── frontier.py      bounded in-memory queue with backpressure
        ├── index_writer.py  write path: persist fetch results, links, postings
        ├── models.py        shared dataclasses and enums
        ├── parser.py        HTML title / text / link extraction
        ├── search_service.py SQL-based term-frequency search
        ├── storage.py       SQLite connection, DDL, migrations, and query helpers
        └── url_normalizer.py canonical URL normalization
```

---

## Companion Documents

| File | Contents |
|---|---|
| `product_prd.md` | Product requirements and feature specification |
| `multi_agent_workflow.md` | Description of the multi-agent development workflow |
| `recommendation.md` | Design decisions, trade-offs, and future recommendations |
| `agents/` | Per-agent role definitions used during development |
| `docs/diagrams.md` | Architecture and workflow diagrams (Mermaid) |

The multi-agent development workflow operated during **development only** and has no effect
on how the runtime application behaves.
