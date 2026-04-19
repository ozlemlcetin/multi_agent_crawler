"""Flask web interface — multi-page crawler console."""

from __future__ import annotations

import os
from pathlib import Path

from flask import Flask, current_app, jsonify, redirect, render_template, request, url_for

from .coordinator import Coordinator
from .coordinator import IndexError as CrawlIndexError

_TEMPLATE_DIR = Path(__file__).parent / "templates"


def create_app() -> Flask:
    flask_app = Flask(__name__, template_folder=str(_TEMPLATE_DIR), static_folder=None)
    flask_app.config["COORDINATOR"] = Coordinator()
    return flask_app


app = create_app()

# ---------------------------------------------------------------------------
# HTML page routes
# ---------------------------------------------------------------------------


@app.get("/")
def root():
    return redirect(url_for("dashboard"))


@app.get("/dashboard")
def dashboard():
    return render_template("dashboard.html", page="dashboard")


@app.get("/jobs")
def jobs_page():
    return render_template("jobs.html", page="jobs")


@app.get("/jobs/<job_id>")
def job_detail_page(job_id: str):
    return render_template("job_detail.html", page="jobs", job_id=job_id)


@app.get("/logs")
def logs_page():
    return render_template("logs.html", page="logs")


@app.get("/errors")
def errors_page():
    return render_template("errors.html", page="errors")


@app.get("/search")
def search_page():
    return render_template("search.html", page="search")


@app.get("/status")
def status_page():
    return render_template("status.html", page="status")


@app.get("/pages")
def pages_page():
    return render_template("pages.html", page="pages")


# ---------------------------------------------------------------------------
# API — system
# ---------------------------------------------------------------------------


@app.get("/api/status")
def api_status():
    return jsonify(current_app.config["COORDINATOR"].status())


@app.get("/api/dashboard")
def api_dashboard():
    return jsonify(current_app.config["COORDINATOR"].get_dashboard_data())


# ---------------------------------------------------------------------------
# API — jobs
# ---------------------------------------------------------------------------


@app.get("/api/jobs")
def api_jobs():
    rows = current_app.config["COORDINATOR"].jobs()
    return jsonify([dict(r) for r in rows])


@app.get("/api/jobs/<job_id>")
def api_job_detail(job_id: str):
    detail = current_app.config["COORDINATOR"].get_job_detail(job_id)
    if detail is None:
        return jsonify({"error": "job not found"}), 404
    return jsonify(detail)


@app.get("/api/jobs/<job_id>/events")
def api_job_events(job_id: str):
    limit = min(int(request.args.get("limit", 200)), 1000)
    events = current_app.config["COORDINATOR"].get_job_events(job_id, limit=limit)
    return jsonify([dict(e) for e in events])


@app.get("/api/jobs/<job_id>/pages")
def api_job_pages(job_id: str):
    fetch_state = request.args.get("fetch_state") or None
    limit = min(int(request.args.get("limit", 200)), 1000)
    rows = current_app.config["COORDINATOR"].get_discovered_pages(
        job_id=job_id, fetch_state=fetch_state, limit=limit
    )
    return jsonify([dict(r) for r in rows])


@app.post("/api/jobs/<job_id>/pause")
def api_job_pause(job_id: str):
    ok = current_app.config["COORDINATOR"].pause(job_id)
    if not ok:
        return jsonify({"error": "job not found or not pausable"}), 400
    return jsonify({"status": "paused"})


@app.post("/api/jobs/<job_id>/resume")
def api_job_resume(job_id: str):
    ok = current_app.config["COORDINATOR"].resume(job_id)
    if not ok:
        return jsonify({"error": "job not found or not paused"}), 400
    return jsonify({"status": "resumed"})


@app.post("/api/jobs/<job_id>/cancel")
def api_job_cancel(job_id: str):
    ok = current_app.config["COORDINATOR"].cancel(job_id)
    if not ok:
        return jsonify({"error": "job not found or already finished"}), 400
    return jsonify({"status": "cancelled"})


@app.post("/api/jobs/<job_id>/retry")
def api_job_retry(job_id: str):
    try:
        job = current_app.config["COORDINATOR"].retry_job(job_id)
    except CrawlIndexError as exc:
        return jsonify({"error": str(exc)}), 400
    if job is None:
        return jsonify({"error": "job not found"}), 404
    return jsonify({"job_id": job.job_id, "origin_url": job.origin_url,
                    "max_depth": job.max_depth, "status": job.status.value})


# ---------------------------------------------------------------------------
# API — search
# ---------------------------------------------------------------------------


@app.get("/api/search")
def api_search():
    q = request.args.get("q", "").strip()
    limit = min(int(request.args.get("limit", 50)), 200)
    if not q:
        return jsonify([])
    results = current_app.config["COORDINATOR"].search(q, limit=limit)
    return jsonify([
        {"relevant_url": r.relevant_url, "origin_url": r.origin_url, "depth": r.depth}
        for r in results
    ])


# ---------------------------------------------------------------------------
# API — logs / errors / pages
# ---------------------------------------------------------------------------


@app.get("/api/logs")
def api_logs():
    job_id     = request.args.get("job_id") or None
    event_type = request.args.get("event_type") or None
    q          = request.args.get("q") or None
    limit      = min(int(request.args.get("limit", 200)), 1000)
    rows = current_app.config["COORDINATOR"].get_global_events(
        limit=limit, job_id=job_id, event_type=event_type, q=q
    )
    return jsonify([dict(r) for r in rows])


@app.get("/api/errors")
def api_errors():
    limit = min(int(request.args.get("limit", 200)), 1000)
    rows = current_app.config["COORDINATOR"].get_failed_pages(limit=limit)
    return jsonify([dict(r) for r in rows])


@app.get("/api/pages")
def api_pages():
    job_id     = request.args.get("job_id") or None
    fetch_state = request.args.get("fetch_state") or None
    raw_depth  = request.args.get("depth")
    depth      = int(raw_depth) if raw_depth and raw_depth.isdigit() else None
    limit      = min(int(request.args.get("limit", 200)), 1000)
    rows = current_app.config["COORDINATOR"].get_discovered_pages(
        job_id=job_id, fetch_state=fetch_state, depth=depth, limit=limit
    )
    return jsonify([dict(r) for r in rows])


# ---------------------------------------------------------------------------
# API — crawl controls
# ---------------------------------------------------------------------------


@app.post("/api/index")
def api_index():
    body = request.get_json(silent=True) or {}
    url = (body.get("url") or "").strip()
    try:
        depth = int(body.get("depth", 1))
    except (TypeError, ValueError):
        return jsonify({"error": "depth must be an integer"}), 400
    try:
        job = current_app.config["COORDINATOR"].index(url, depth)
    except CrawlIndexError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"job_id": job.job_id, "origin_url": job.origin_url,
                    "max_depth": job.max_depth, "status": job.status.value})


@app.post("/api/run")
def api_run():
    coord = current_app.config["COORDINATOR"]
    if not coord.try_start_run():
        return jsonify({"error": "a run is already in progress"}), 409
    try:
        summary = coord.run_until_idle()
    finally:
        coord.finish_run()
    return jsonify(summary)


@app.post("/api/step")
def api_step():
    result = current_app.config["COORDINATOR"].step()
    return jsonify({
        "processed":       result.processed,
        "url":             result.url,
        "outcome":         result.outcome,
        "title":           result.title,
        "links_found":     result.links_found,
        "children_admitted": result.children_admitted,
        "error":           result.error,
        "skipped_paused":  result.skipped_paused,
    })


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)


if __name__ == "__main__":
    main()
