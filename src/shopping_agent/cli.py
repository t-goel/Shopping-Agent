"""Run from a checkout: PYTHONPATH=src python -m shopping_agent.cli ..."""
import argparse
import json
from pathlib import Path

from shopping_agent.eval.report import read_records, summarize
from shopping_agent.eval.runner import ROOT, load_store_modules, run_suite

DEFAULT_INGEST = ROOT / "mock-store/server/examples/ingest.example.json"
DEFAULT_STORES_TASKS = ROOT / "data/tasks/stores"
DEFAULT_FLAT_CATALOG = ROOT / "mock-store/server/examples/catalog.json"
DEFAULT_FLAT_TASKS = ROOT / "data/tasks"


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


def main():
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
    run.add_argument("--seed", type=int, default=498)
    run.add_argument("--max-calls", type=positive_int, default=20)
    run.add_argument("--timeout", type=positive_seconds, default=60)
    run.add_argument("--agent", choices=("rules", "claude"), default="rules")
    report = commands.add_parser("report")
    report.add_argument("input", type=Path)
    args = parser.parse_args()
    if args.command == "run":
        _, _, _, load_examples, load_multi_store_examples = load_store_modules()
        if args.mode == "multi-store":
            catalog_path = args.catalog or DEFAULT_INGEST
            tasks_path = args.tasks or DEFAULT_STORES_TASKS
            catalog, tasks = load_multi_store_examples(catalog_path, tasks_path)
        else:
            catalog_path = args.catalog or DEFAULT_FLAT_CATALOG
            tasks_path = args.tasks or DEFAULT_FLAT_TASKS
            catalog, tasks = load_examples(catalog_path, tasks_path)
        run_suite(
            catalog,
            tasks,
            args.output,
            args.repetitions,
            args.seed,
            args.max_calls,
            args.timeout,
            args.agent,
        )
        path = args.output
    else:
        path = args.input
    print(json.dumps(summarize(read_records(path)), indent=2))


if __name__ == "__main__":
    main()
