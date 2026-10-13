"""Run from a checkout: PYTHONPATH=src python -m shopping_agent.cli ..."""
import argparse
import json
from pathlib import Path

from shopping_agent.eval.report import read_records, summarize
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


def main():
    parser = argparse.ArgumentParser(description="Deterministic mock-store evaluation pilot")
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run")
    run.add_argument("--tasks", type=Path, default=ROOT / "data/tasks")
    run.add_argument("--catalog", type=Path, default=ROOT / "mock-store/server/examples/catalog.json")
    run.add_argument("--output", type=Path, required=True)
    run.add_argument("--repetitions", type=positive_int, default=3)
    run.add_argument("--seed", type=int, default=498)
    run.add_argument("--max-calls", type=positive_int, default=10)
    run.add_argument("--timeout", type=positive_seconds, default=60)
    report = commands.add_parser("report")
    report.add_argument("input", type=Path)
    args = parser.parse_args()
    if args.command == "run":
        _, _, load_examples = load_store_modules()
        catalog, tasks = load_examples(args.catalog, args.tasks)
        run_suite(catalog, tasks, args.output, args.repetitions, args.seed, args.max_calls, args.timeout)
        path = args.output
    else:
        path = args.input
    print(json.dumps(summarize(read_records(path)), indent=2))


if __name__ == "__main__":
    main()
