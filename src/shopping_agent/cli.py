"""Run from a checkout: PYTHONPATH=src python -m shopping_agent.cli ..."""
import argparse
import json
from pathlib import Path

from shopping_agent.eval.audit import audit_path
from shopping_agent.eval.report import (
    markdown_report,
    print_run_summary,
    print_trial_line,
    read_records,
    summarize,
)
from shopping_agent.eval.runner import ROOT, load_store_modules, run_suite


def positive_int(value):
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be positive")
    return number


def positive_seconds(value):
    import math
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError("must be finite and positive")
    return number


def main(argv=None):
    parser = argparse.ArgumentParser(description="Deterministic mock-store evaluation pilot")
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run")
    run.add_argument(
        "--mode",
        choices=("multi-store", "flat"),
        default="multi-store",
        help="multi-store is the default harder suite; flat keeps the single-catalog NL suite",
    )
    run.add_argument("--tasks", type=Path, default=None)
    run.add_argument("--catalog", type=Path, default=None)
    run.add_argument("--output", type=Path, required=True)
    run.add_argument("--repetitions", type=positive_int, default=3)
    run.add_argument("--seed", type=int, default=49)
    run.add_argument("--max-calls", type=positive_int, default=20)
    run.add_argument("--timeout", type=positive_seconds, default=60)
    run.add_argument("--agent", choices=("rules", "claude"), default="rules")
    run.add_argument("--json", action="store_true", help="Emit machine-readable JSON summary")
    report = commands.add_parser("report")
    report.add_argument("input", type=Path)
    report.add_argument("--json", action="store_true", help="Emit machine-readable JSON summary")
    report.add_argument("--markdown", action="store_true", help="Print per-task evidence and failure categories")
    audit = commands.add_parser("audit", help="Read-only claim/cart audit of saved trial JSONL")
    audit.add_argument("input", type=Path, help="Saved trial JSONL; no API key needed")
    args = parser.parse_args(argv)

    if args.command == "audit":
        print(json.dumps(audit_path(args.input), indent=2, ensure_ascii=True))
        return 0

    if args.command == "run":
        _, _, _, load_examples, load_multi_store_examples = load_store_modules()
        if args.mode == "multi-store":
            catalog_path = args.catalog or (ROOT / "mock-store/server/examples/ingest.example.json")
            tasks_path = args.tasks or (ROOT / "data/tasks/stores")
            catalog, tasks = load_multi_store_examples(catalog_path, tasks_path)
        else:
            catalog_path = args.catalog or (ROOT / "mock-store/server/examples/catalog.json")
            tasks_path = args.tasks or (ROOT / "data/tasks")
            catalog, tasks = load_examples(catalog_path, tasks_path)
        records = run_suite(
            catalog, tasks, args.output, args.repetitions, args.seed,
            args.max_calls, args.timeout, args.agent,
            on_result=None if args.json else print_trial_line,
        )
    else:
        records = read_records(args.input)

    if getattr(args, "markdown", False):
        print(markdown_report(records))
    elif args.json:
        print(json.dumps(summarize(records), indent=2))
    elif args.command == "run":
        print_run_summary(records, include_trials=False)
    else:
        print_run_summary(records)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
