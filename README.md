# multi_agent_crawler

A local Python web crawler and search system built as a course project.
The runtime is a plain single-process Python application with a CLI and an optional local web interface.
The "multi-agent" aspect refers to the **development workflow** only (see companion docs below).

---

## Overview

`multi_agent_crawler` crawls HTTP/HTTPS websites, indexes page content into a local SQLite
database, and lets you search indexed pages from an interactive CLI shell or a local web UI.
Everything runs on localhost — no external services required.

---

## Core Features

- **Interactive CLI shell** — `index`, `step`, `run`, `search`, `jobs`, `status`, `quit`
- **Local web UI** — Flask-based browser interface with the same index / step / run / search / jobs / status actions
- **URL canonicalization** — scheme/host lowercasing, default-port stripping, fragment removal, relative-URL resolution
- **Synchronous page fetcher** — stdlib `urllib`, redirect following, charset-aware decoding, configurable byte cap
- **HTML parser** — title extraction, visible-text collection, link extraction, script/style suppression
- **Bounded frontier queue** — in-memory `queue.Queue` with configurable max size and backpressure flag
- **SQLite persistence** — WAL mode, 6-table schema; write path serialised by a lock, reads served from a dedicated second connection
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
                                └── SQLite DB — WAL, 6 tables             (storage.py)
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
| `search <query>` | Search indexed pages; terms are OR-matched, results show `(relevant_url, origin_url, depth)` |
| `jobs` | List all crawl jobs with id, status, depth, creation time, and origin URL |
| `status` | Show frontier size/capacity/backpressure and DB row counts |
| `help` | Print command reference |
| `quit` / `exit` / `q` | Exit the shell |

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
| `crawl_jobs` | One row per `index` call; tracks origin URL, max depth, status |
| `pages` | One row per canonical URL; tracks fetch state, HTTP status, title, content hash |
| `discoveries` | Maps `(job_id, page_id)` to depth and parent; min-depth wins on conflict |
| `page_links` | Outgoing links extracted from each fetched HTML page |
| `terms` | Deduplicated vocabulary across all indexed pages |
| `postings` | `(term_id, page_id, term_frequency)` — the inverted index |

The frontier queue is **in-memory only** and is not restored across sessions.
If the program exits, queued-but-unprocessed work is lost for that session.

---

## Known Limitations / MVP Boundaries

- **CLI is synchronous** — `step` and `run` block in the terminal; pages are processed one at a time. The web server handles search/status concurrently via Flask threading, but indexing itself is still single-threaded (one page fetched at a time).
- **No frontier recovery** — the in-memory queue is lost on exit; queued-but-unprocessed work is not restored on restart.
- **No recrawl support** — already-fetched pages are not re-fetched in a new session.
- **No TF-IDF or PageRank** — search ranking uses raw term frequency and match count only.
- **No crawl politeness framework** — no `robots.txt` handling or per-host pacing is implemented (the frontier does signal backpressure at 80% capacity, but this is not a substitute for a real politeness layer).
- **HTTP/HTTPS only** — `mailto:`, `ftp:`, `javascript:`, and other schemes are discarded.
- **Single process** — `max_workers` in config is reserved for parallel crawl workers; the request-handling threading in the web server is already active but does not parallelize fetching.
- **Web UI is local/dev only** — the Flask server is a development convenience, not a production deployment.

---

## Repository Structure

```
multi_agent_crawler/
├── pyproject.toml
└── src/
    └── crawler_search/
        ├── __init__.py          package entry point
        ├── cli.py               interactive shell and argparse entry point
        ├── web.py               Flask web UI and REST API (optional)
        ├── templates/
        │   └── index.html       single-page browser interface
        ├── config.py            Config dataclass with defaults
        ├── coordinator.py       orchestrates index / step / search / status
        ├── fetcher.py           synchronous HTTP fetch
        ├── frontier.py          bounded in-memory queue with backpressure
        ├── index_writer.py      write path: persist fetch results, links, postings
        ├── models.py            shared dataclasses and enums
        ├── parser.py            HTML title / text / link extraction
        ├── search_service.py    SQL-based term-frequency search
        ├── storage.py           SQLite connection, DDL, and query helpers
        └── url_normalizer.py    canonical URL normalization
```

---

## Companion Documents

The following documents describe aspects of this project that are **not** part of the runtime system:

| File | Contents |
|---|---|
| `product_prd.md` | Product requirements and feature specification |
| `multi_agent_workflow.md` | Description of the multi-agent development workflow used to build this project patch-by-patch |
| `recommendation.md` | Design decisions, trade-offs, and recommendations for future development |

The multi-agent development workflow — in which multiple AI tools and chat sessions coordinated
patch-by-patch implementation — is a **development-time process only** and has no effect on how
the runtime application behaves.
