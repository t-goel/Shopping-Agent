"""Run from a checkout: PYTHONPATH=src python -m shopping_agent.cli ..."""
import argparse
import json
from pathlib import Path

from shopping_agent.agent.baselines import CONDITIONS
from shopping_agent.eval.audit import audit_path
from shopping_agent.eval.compare import (
    comparison,
    csv_text,
    markdown_table,
    protocol_lines,
)
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


def seed_list(value):
    try:
        seeds = [int(part.strip()) for part in value.split(",") if part.strip()]
    except ValueError as exc:
        raise argparse.ArgumentTypeError("seeds must be comma-separated integers") from exc
    if not seeds:
        raise argparse.ArgumentTypeError("at least one seed is required")
    return seeds


def load_suite(mode, tasks_path=None, catalog_path=None):
    _, _, _, load_examples, load_multi_store_examples = load_store_modules()
    if mode == "multi-store":
        catalog = catalog_path or (ROOT / "mock-store/server/examples/ingest.example.json")
        tasks = tasks_path or (ROOT / "data/tasks/stores")
        return load_multi_store_examples(catalog, tasks)
    catalog = catalog_path or (ROOT / "mock-store/server/examples/catalog.json")
    tasks = tasks_path or (ROOT / "data/tasks")
    return load_examples(catalog, tasks)


def run_comparison(args, parser):
    conditions = [item.strip() for item in args.conditions.split(",") if item.strip()]
    unknown = [item for item in conditions if item not in CONDITIONS]
    if not conditions or unknown:
        parser.error(f"--conditions must be a nonempty subset of: {', '.join(CONDITIONS)}")
    if args.output_dir.exists():
        parser.error(f"{args.output_dir} already exists; choose a new output directory")

    catalog, tasks = load_suite(args.mode, args.tasks, args.catalog)
    args.output_dir.mkdir(parents=True)
    paths = {}
    for condition in conditions:
        path = args.output_dir / f"{condition}.jsonl"
        run_suite(
            catalog, tasks, path,
            agent_name=condition,
            seeds=args.seeds,
            max_calls=args.max_calls,
            seconds=args.timeout,
            max_turns=args.max_turns,
        )
        paths[condition] = path

    result = comparison(
        paths,
        protocol_note=(
            "Offline deterministic model surrogates; no Anthropic API key was used. "
            "A live provider-backed run uses --agent claude and is reported separately."
        ),
    )
    (args.output_dir / "comparison.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (args.output_dir / "comparison.csv").write_text(csv_text(result), encoding="utf-8")
    table = markdown_table(result)
    (args.output_dir / "table1.md").write_text(
        "# Table 1: natural-language suite by condition\n\n"
        + table + "\n\n## Protocol\n\n"
        + "\n".join(protocol_lines(result)) + "\n",
        encoding="utf-8",
    )
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(table)
    return 0


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
    run.add_argument(
        "--seeds", type=seed_list, default=None,
        help="comma-separated per-trial seeds (e.g. 1,2,3); overrides --seed/--repetitions",
    )
    run.add_argument("--max-calls", type=positive_int, default=20)
    run.add_argument(
        "--max-turns", type=positive_int, default=None,
        help="Claude ReAct model-turn budget; defaults to --max-calls + 1",
    )
    run.add_argument("--timeout", type=positive_seconds, default=60)
    run.add_argument(
        "--agent", choices=("rules", "claude") + CONDITIONS, default="rules",
        help="offline conditions: " + ", ".join(CONDITIONS),
    )
    run.add_argument("--json", action="store_true", help="Emit machine-readable JSON summary")
    report = commands.add_parser("report")
    report.add_argument("input", type=Path)
    report.add_argument("--json", action="store_true", help="Emit machine-readable JSON summary")
    report.add_argument("--markdown", action="store_true", help="Print per-task evidence and failure categories")
    audit = commands.add_parser("audit", help="Read-only claim/cart audit of saved trial JSONL")
    audit.add_argument("input", type=Path, help="Saved trial JSONL; no API key needed")
    compare_cmd = commands.add_parser(
        "compare", help="Run the NL-suite baseline matrix across three seeds and build Table 1",
    )
    compare_cmd.add_argument(
        "--output-dir", type=Path, required=True,
        help="new directory for per-condition JSONL, comparison.json, comparison.csv, table1.md",
    )
    compare_cmd.add_argument("--mode", choices=("multi-store", "flat"), default="flat")
    compare_cmd.add_argument("--tasks", type=Path, default=None)
    compare_cmd.add_argument("--catalog", type=Path, default=None)
    compare_cmd.add_argument("--seeds", type=seed_list, default=[1, 2, 3])
    compare_cmd.add_argument("--conditions", default=",".join(CONDITIONS))
    compare_cmd.add_argument("--max-calls", type=positive_int, default=20)
    compare_cmd.add_argument(
        "--max-turns", type=positive_int, default=None,
        help="Claude ReAct model-turn budget; defaults to --max-calls + 1",
    )
    compare_cmd.add_argument("--timeout", type=positive_seconds, default=60)
    compare_cmd.add_argument("--json", action="store_true", help="Emit machine-readable JSON summary")
    args = parser.parse_args(argv)

    if args.command == "audit":
        print(json.dumps(audit_path(args.input), indent=2, ensure_ascii=True))
        return 0

    if args.command == "compare":
        return run_comparison(args, parser)

    if args.command == "run":
        catalog, tasks = load_suite(args.mode, args.tasks, args.catalog)
        records = run_suite(
            catalog, tasks, args.output, args.repetitions, args.seed,
            args.max_calls, args.timeout, args.agent,
            seeds=args.seeds,
            max_turns=args.max_turns,
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
