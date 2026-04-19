"""
Integration demo: proves search and status return while /api/run is actively crawling.

This is NOT a pytest unit test — it has no test_ functions and is not collected
by pytest.  It is a standalone demo script that must be run directly:

    python tests/test_concurrent.py

Requirements:
  - flask must be installed  (pip install -e ".[web]")
  - No server already running on port 5001
  - Active internet connection (crawls https://example.com)

For automated CI, use tests/test_core.py instead (offline, deterministic).
"""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request


BASE = "http://localhost:5001"
RESULTS: dict = {}


def _post(path: str, body: bytes = b"", content_type: str = "application/json") -> dict:
    req = urllib.request.Request(
        BASE + path,
        data=body,
        method="POST",
        headers={"Content-Type": content_type},
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read())


def _get(path: str) -> dict | list:
    with urllib.request.urlopen(BASE + path, timeout=10) as resp:
        return json.loads(resp.read())


def _wait_for_server(retries: int = 20, delay: float = 0.5) -> None:
    for _ in range(retries):
        try:
            _get("/api/status")
            return
        except Exception:
            time.sleep(delay)
    raise RuntimeError("server did not start in time")


# ---------------------------------------------------------------------------
# Thread targets
# ---------------------------------------------------------------------------

def thread_run():
    RESULTS["run_start"] = time.monotonic()
    try:
        data = _post("/api/run")
        RESULTS["run_end"] = time.monotonic()
        RESULTS["run_data"] = data
    except Exception as exc:
        RESULTS["run_end"] = time.monotonic()
        RESULTS["run_error"] = str(exc)


def thread_search():
    # Give /api/run a moment to start its first fetch before probing.
    time.sleep(0.8)
    RESULTS["search_start"] = time.monotonic()
    try:
        data = _get("/api/search?q=example")
        RESULTS["search_end"] = time.monotonic()
        RESULTS["search_data"] = data
    except Exception as exc:
        RESULTS["search_end"] = time.monotonic()
        RESULTS["search_error"] = str(exc)


def thread_status():
    time.sleep(1.2)
    RESULTS["status_start"] = time.monotonic()
    try:
        data = _get("/api/status")
        RESULTS["status_end"] = time.monotonic()
        RESULTS["status_data"] = data
    except Exception as exc:
        RESULTS["status_end"] = time.monotonic()
        RESULTS["status_error"] = str(exc)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    import os, pathlib
    # Clean slate
    db = pathlib.Path("crawler.db")
    for ext in ("", "-wal", "-shm"):
        p = db.with_suffix(db.suffix + ext) if ext else db
        p.unlink(missing_ok=True)

    print("Starting server …")
    env = os.environ.copy()
    env["PORT"] = "5001"
    server = subprocess.Popen(
        [sys.executable, "-m", "crawler_search.web"],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        _wait_for_server()
        print("Server ready.")

        # Index example.com at depth 2 to get enough pages for a multi-second run.
        job = _post("/api/index", json.dumps({"url": "https://example.com", "depth": 2}).encode())
        print(f"Job created: {job['job_id']}  depth={job['max_depth']}")

        # Launch run + concurrent read probes in parallel.
        t_run    = threading.Thread(target=thread_run,    daemon=True)
        t_search = threading.Thread(target=thread_search, daemon=True)
        t_status = threading.Thread(target=thread_status, daemon=True)

        t_run.start()
        t_search.start()
        t_status.start()

        t_run.join()
        t_search.join()
        t_status.join()

    finally:
        server.terminate()
        server.wait()

    # ------------------------------------------------------------------
    # Report
    # ------------------------------------------------------------------
    print()
    print("=" * 60)
    print("TIMING RESULTS  (monotonic seconds from process start)")
    print("=" * 60)

    run_start  = RESULTS.get("run_start", 0)
    run_end    = RESULTS.get("run_end", 0)
    srch_start = RESULTS.get("search_start", 0)
    srch_end   = RESULTS.get("search_end", 0)
    stat_start = RESULTS.get("status_start", 0)
    stat_end   = RESULTS.get("status_end", 0)

    run_dur  = run_end  - run_start
    srch_dur = srch_end - srch_start
    stat_dur = stat_end - stat_start

    print(f"  /api/run    started={run_start:.3f}  ended={run_end:.3f}  duration={run_dur:.2f}s")
    print(f"  /api/search started={srch_start:.3f}  ended={srch_end:.3f}  duration={srch_dur:.3f}s")
    print(f"  /api/status started={stat_start:.3f}  ended={stat_end:.3f}  duration={stat_dur:.3f}s")

    search_concurrent = run_start < srch_start < srch_end < run_end
    status_concurrent = run_start < stat_start < stat_end < run_end

    print()
    print("CONCURRENT PROOF")
    print(f"  search returned WHILE run was active : {'PASS ✓' if search_concurrent else 'FAIL ✗'}")
    print(f"  status returned WHILE run was active : {'PASS ✓' if status_concurrent else 'FAIL ✗'}")

    print()
    print("SEARCH RESULTS during crawl:")
    for r in RESULTS.get("search_data", [])[:3]:
        print(f"  {r}")

    print()
    print("STATUS snapshot during crawl:")
    s = RESULTS.get("status_data", {})
    print(f"  pages_total={s.get('pages_total')}  frontier_size={s.get('frontier_size')}  "
          f"backpressure={s.get('backpressure')}")

    print()
    print("RUN summary:")
    print(f"  {RESULTS.get('run_data', RESULTS.get('run_error'))}")

    ok = search_concurrent and status_concurrent
    print()
    print("VERDICT:", "ALL PASS ✓" if ok else "FAILED ✗")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
