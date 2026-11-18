"""Pool per-condition trial files into one comparison table (Table 1).

Conditions are never pooled with each other: each JSONL file must contain a
single agent condition, and the comparison keeps them as separate rows.
"""

from __future__ import annotations

from pathlib import Path

from shopping_agent.contracts import TrialResult
from shopping_agent.eval.report import read_records, summarize

CONDITION_LABELS = {
    "single_prompt": "Single-prompt LLM",
    "react": "Vanilla ReAct",
    "no_verifier": "Proposed agent (no-verifier ablation)",
    "full": "Proposed agent (with verification gate)",
}

COLUMNS = (
    ("label", "Condition"),
    ("success", "Successful / trials"),
    ("success_rate", "Success rate"),
    ("median_tool_calls", "Median calls"),
    ("median_duration_seconds", "Median seconds"),
    ("p95_duration_seconds", "p95 seconds"),
    ("evidence_trials", "Trials with claim evidence"),
)


def load_conditions(paths: dict[str, Path]) -> dict[str, list[TrialResult]]:
    loaded: dict[str, list[TrialResult]] = {}
    for condition, path in paths.items():
        records = read_records(path)
        if not records:
            raise ValueError(f"{path}: no trial records")
        found = {record.agent_name for record in records}
        if found != {condition}:
            raise ValueError(
                f"{path}: expected only {condition!r} trials, found {sorted(found)}; "
                "do not pool conditions"
            )
        loaded[condition] = records
    return loaded


def comparison(paths: dict[str, Path], *, protocol_note: str | None = None) -> dict:
    """Build a comparison-ready summary from per-condition JSONL files."""

    loaded = load_conditions(paths)
    rows = {}
    for condition, records in loaded.items():
        report = summarize(records)
        overall = report["overall"]
        identity = report["identity"]
        rows[condition] = {
            "condition": condition,
            "label": CONDITION_LABELS.get(condition, condition),
            "agent_name": identity["agent_name"],
            "model_id": identity["model_id"],
            "prompt_id": identity["prompt_id"],
            "agent_surface": identity["agent_surface"],
            "trials": overall["trials"],
            "successful": overall["successful"],
            "success_rate": overall["success_rate"],
            "median_tool_calls": overall["median_tool_calls"],
            "median_duration_seconds": overall["median_duration_seconds"],
            "p95_duration_seconds": overall["p95_duration_seconds"],
            "evidence_trials": sum(bool(record.evidence) for record in records),
            "failure_categories": overall["failure_categories"],
            "termination_reasons": overall["termination_reasons"],
        }

    first = next(iter(loaded.values()))
    sample = first[0].run_metadata
    seeds = sorted({record.run_metadata.get("seed") for record in first if record.run_metadata.get("seed") is not None})
    tasks = sorted({record.task_id for record in first})
    return {
        "conditions": rows,
        "protocol": {
            "tasks": tasks,
            "task_count": len(tasks),
            "seeds": seeds,
            "trials_per_condition": len(first),
            "max_tool_calls": sample.get("max_tool_calls"),
            "timeout_seconds": sample.get("timeout_seconds"),
            "source_sha256": sample.get("source_sha256"),
            "git_commit": sample.get("git_commit"),
            "agent_surface": sample.get("agent_surface"),
            "note": protocol_note,
        },
    }


def _rate(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.1f}%"


def _seconds(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.4f}"


def markdown_table(result: dict) -> str:
    lines = [
        "| Condition | Successful / trials | Success rate | Median calls | Median seconds | p95 seconds | Trials with claim evidence |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in result["conditions"].values():
        lines.append(
            f"| {row['label']} | {row['successful']}/{row['trials']} | {_rate(row['success_rate'])} | "
            f"{row['median_tool_calls']} | {_seconds(row['median_duration_seconds'])} | "
            f"{_seconds(row['p95_duration_seconds'])} | {row['evidence_trials']}/{row['trials']} |"
        )
    return "\n".join(lines)


def csv_text(result: dict) -> str:
    lines = [",".join(f'"{header}"' for _, header in COLUMNS)]
    for row in result["conditions"].values():
        values = {
            "label": row["label"],
            "success": f"{row['successful']}/{row['trials']}",
            "success_rate": _rate(row["success_rate"]),
            "median_tool_calls": row["median_tool_calls"],
            "median_duration_seconds": row["median_duration_seconds"],
            "p95_duration_seconds": row["p95_duration_seconds"],
            "evidence_trials": f"{row['evidence_trials']}/{row['trials']}",
        }
        lines.append(",".join(str(values[key]) for key, _ in COLUMNS))
    return "\n".join(lines) + "\n"


def protocol_lines(result: dict) -> list[str]:
    protocol = result["protocol"]
    lines = [
        f"- Tasks: {protocol['task_count']} natural-language tasks",
        f"- Seeds: {', '.join(str(seed) for seed in protocol['seeds'])} "
        f"({len(protocol['seeds'])} per task)",
        f"- Trials per condition: {protocol['trials_per_condition']}",
        f"- Limits: {protocol['max_tool_calls']} tool calls, {protocol['timeout_seconds']} seconds per trial",
        f"- Source SHA-256: `{protocol['source_sha256']}`",
    ]
    if protocol.get("note"):
        lines.append(f"- Note: {protocol['note']}")
    return lines
