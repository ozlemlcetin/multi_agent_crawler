"""CLI entry point and interactive shell."""

from __future__ import annotations

import argparse
import shlex
import sys

from .coordinator import Coordinator, IndexError

_SEP = "─" * 72


def _hr() -> None:
    print(_SEP)


def _print_help() -> None:
    _hr()
    print("  crawler-search — local web crawler and search system")
    _hr()
    print("  Commands")
    print()
    print("    index <url> <depth>    Queue <url> as a new crawl job up to <depth> hops")
    print("    step                   Fetch + index one queued page (synchronous)")
    print("    jobs                   List all crawl jobs")
    print("    status                 Show counts and frontier state")
    print("    search <query>         Search indexed pages  (space-separated terms OR'd)")
    print("    help                   Show this message")
    print("    quit  /  exit  /  q    Exit the shell")
    _hr()


def _fmt_row(cols: list[tuple[str, int]]) -> str:
    return "  " + "  ".join(f"{val:<{w}}" for val, w in cols)


def run_shell(coordinator: Coordinator) -> None:
    print()
    print("  crawler-search shell  —  type  help  for commands,  quit  to exit")
    print()
    while True:
        try:
            raw = input(">>> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not raw:
            continue

        try:
            parts = shlex.split(raw)
        except ValueError as exc:
            print(f"  parse error: {exc}")
            continue

        cmd, *args = parts

        # ── quit ──────────────────────────────────────��───────────────────
        if cmd in ("quit", "exit", "q"):
            break

        # ── help ──────────────────────────────────────────────────────────
        elif cmd == "help":
            _print_help()

        # ── index ─────────────────────────────────────────────────────────
        elif cmd == "index":
            if len(args) != 2:
                print("  usage: index <url> <depth>")
                continue
            origin, k_str = args
            try:
                k = int(k_str)
            except ValueError:
                print(f"  error: <depth> must be an integer, got {k_str!r}")
                continue
            try:
                job = coordinator.index(origin, k)
            except IndexError as exc:
                print(f"  error: {exc}")
                continue
            print(f"  job created  id={job.job_id}  depth={job.max_depth}  url={job.origin_url}")

        # ── step ──────────────────────────────────────────────────────────
        elif cmd == "step":
            r = coordinator.step()
            if not r.processed:
                print("  frontier is empty — nothing to process")
            else:
                outcome_tag = f"[{r.outcome}]"
                print(f"  {outcome_tag:<20}  {r.url}")
                if r.title:
                    print(f"  {'title':<20}  {r.title!r}")
                print(f"  {'links found':<20}  {r.links_found}")
                print(f"  {'children admitted':<20}  {r.children_admitted}")
                if r.error:
                    print(f"  {'error':<20}  {r.error}")

        # ── search ─────────────────────────────────��──────────────────────
        elif cmd == "search":
            if not args:
                print("  usage: search <query terms>")
                continue
            query = " ".join(args)
            results = coordinator.search(query)
            if not results:
                print("  (no results)")
            else:
                hdr = _fmt_row([("relevant_url", 48), ("origin_url", 36), ("depth", 5)])
                div = _fmt_row([("─" * 48, 48), ("─" * 36, 36), ("─" * 5, 5)])
                print(hdr)
                print(div)
                for r in results:
                    print(_fmt_row([(r.relevant_url, 48), (r.origin_url, 36), (str(r.depth), 5)]))

        # ── status ───────────────────────────���────────────────────────────
        elif cmd == "status":
            info = coordinator.status()
            snap_keys = ("frontier_size", "frontier_capacity", "backpressure")
            db_keys = (
                "crawl_jobs", "pages", "discoveries",
                "page_links", "terms", "postings",
            )
            print()
            print("  Frontier")
            for k in snap_keys:
                label = k.replace("_", " ")
                print(f"    {label:<22}  {info[k]}")
            print()
            print("  Database")
            for k in db_keys:
                full_key = f"{k}_total"
                label = k.replace("_", " ")
                print(f"    {label:<22}  {info[full_key]}")
            print()

        # ── jobs ──────────────────────────────────────────────────────────
        elif cmd == "jobs":
            jobs = coordinator.jobs()
            if not jobs:
                print("  (no jobs)")
            else:
                hdr = _fmt_row([
                    ("job_id", 12), ("status", 9), ("depth", 5),
                    ("created_at", 26), ("origin_url", 0),
                ])
                div = _fmt_row([
                    ("─" * 12, 12), ("─" * 9, 9), ("─" * 5, 5),
                    ("─" * 26, 26), ("─" * 20, 0),
                ])
                print(hdr)
                print(div)
                for j in jobs:
                    created = (j["created_at"] or "")[:19].replace("T", " ")
                    print(_fmt_row([
                        (j["job_id"], 12),
                        (j["status"], 9),
                        (str(j["max_depth"]), 5),
                        (created, 26),
                        (j["origin_url"], 0),
                    ]))

        # ── unknown ───────────────────────────────��───────────────────────
        else:
            print(f"  unknown command: {cmd!r}   (type  help  to see available commands)")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="crawler-search",
        description="Local web crawler and search system.",
    )
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("run", help="Start the interactive shell")

    args = parser.parse_args(argv)

    if args.command == "run":
        coordinator = Coordinator()
        run_shell(coordinator)
    else:
        parser.print_help()
        sys.exit(0)


if __name__ == "__main__":
    main()
