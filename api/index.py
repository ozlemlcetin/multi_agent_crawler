"""
Vercel serverless entry point for the multi_agent_crawler web UI.

IMPORTANT LIMITATIONS — read before deploying:

1. SQLite state is ephemeral.  Vercel serverless functions do not share a
   persistent filesystem between invocations.  The database is stored in /tmp,
   which is local to each function instance and discarded when the instance
   is recycled.  All crawl history, indexed pages, and search data will be
   lost whenever Vercel cold-starts a new instance.

2. Active crawling is not supported.  The /api/run and /api/step endpoints
   perform synchronous HTTP fetches that can take tens of seconds.  Vercel
   Hobby and Pro plans enforce a 10-second (Hobby) or 60-second (Pro) function
   execution limit.  Crawling large sites will time out.

3. Outbound network access may be restricted on some Vercel plan tiers.

4. No background workers.  The crawler is single-process and synchronous;
   there is no way to run crawl jobs in the background on a serverless platform.

INTENDED USE:
This deployment is useful only for demonstrating the web UI structure with a
fresh (empty) database.  It is NOT a substitute for the local Python runtime,
which remains the primary and fully-functional mode for this project.

For full functionality, run locally:
    pip install -e ".[web]"
    PORT=5001 crawler-search-web
"""

import os
import sys

# Make the src package importable from the project root.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

# Route the database to /tmp so writes succeed on Vercel's read-only filesystem.
os.environ.setdefault("CRAWLER_DB_PATH", "/tmp/crawler.db")

from crawler_search.web import app  # noqa: E402  (import after sys.path setup)

# Vercel looks for a module-level variable named `app` or `handler`.
__all__ = ["app"]
