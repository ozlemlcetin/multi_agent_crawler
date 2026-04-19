# Deployment

## Primary runtime: local Python (recommended)

The intended and fully functional deployment mode is a plain local Python process.
All features — indexing, crawling, search, job controls, the multi-page web UI —
work correctly in this mode.

```bash
# Install (core CLI, no third-party deps)
pip install -e .

# Install with optional web UI
pip install -e ".[web]"

# Run the CLI
crawler-search run

# Run the web UI
PORT=5001 crawler-search-web
# then open http://localhost:5001
```

The database (`crawler.db`) is created in the working directory on first run.

---

## Optional: Vercel deployment (demo only — significant limitations)

A minimal Vercel deployment path is provided for previewing the web UI.
This is a secondary, optional deployment mode with important limitations.

### Files added for Vercel

| File | Purpose |
|---|---|
| `vercel.json` | Routes all requests to the Flask WSGI handler |
| `api/index.py` | Entry point; configures `/tmp` DB path and imports the Flask app |
| `requirements.txt` | Lists `flask>=3.0` so Vercel's Python builder installs it |

### How to deploy to Vercel

```bash
npm i -g vercel   # if not already installed
vercel            # follow prompts, connect to GitHub, or deploy from CLI
```

### Known limitations of the Vercel deployment

**SQLite state is ephemeral.**
Vercel serverless functions do not maintain a persistent filesystem between
invocations.  The database lives in `/tmp`, which is instance-local and
discarded whenever Vercel cold-starts a new function instance.  All crawl
history, indexed pages, and search results are lost on cold start.

**Crawling will time out.**
`/api/run` and `/api/step` perform synchronous HTTP fetches.  Vercel Hobby
plan enforces a 10-second function timeout; Pro enforces 60 seconds.
Crawling any non-trivial site will exceed this limit.

**No background workers.**
The crawler is single-process and synchronous.  There is no mechanism to
run crawl jobs in the background on a serverless platform.

**Outbound network access.**
Vercel Hobby plans may restrict outbound HTTP connections, which the crawler
requires.

### What the Vercel deployment is useful for

- Previewing the web UI layout and navigation structure with an empty database.
- Demonstrating the multi-page crawler console interface without running anything locally.

### What it is NOT useful for

- Any actual crawling or indexing.
- Persistent search results across page loads.
- Anything requiring a real crawl job to complete.

### Honest summary

The Vercel deployment demonstrates the web UI only.  It is not a production
deployment of the crawler.  The local Python runtime is the only mode in which
the full system works correctly.  This limitation is inherent to the project
architecture (synchronous, file-based SQLite, long-running fetches) and cannot
be resolved without a significant rewrite that is out of scope for this project.
