"""Read-only summaries; unavailable measurements stay null."""

from __future__ import annotations

import math
import os
import sys
from collections import Counter
from statistics import median

from shopping_agent.contracts import TrialResult

_GREEN = "\033[32m"
_RED = "\033[31m"
_BOLD = "\033[1m"
_DIM = "\033[2m"
_RESET = "\033[0m"


def failure_category(record):
    """Observable outcome categories, not speculative model root causes."""
    if record.is_successful:
        return None
    if record.error:
        return record.termination_reason
    if record.termination_reason in {"timeout", "max_tool_calls_exceeded", "unrecoverable_failure"}:
        return record.termination_reason
    if record.expected_kind == "clarification":
        return "clarification_mismatch"
    if record.termination_reason == "clarification_needed":
        # Product-task clarifications are unexpected asks, not constraint failures.
        return "unexpected_clarification"
    if record.termination_reason == "no_valid_product":
        # Only a false abstention when a product selection was required.
        if record.expected_kind == "product":
            return "incorrect_abstention"
        return "abstention_mismatch"
    if record.expected_kind == "product" and record.constraints_satisfied < record.total_constraints:
        return "hard_constraint_violation"
    return "selection_or_cart_mismatch"


def _condition_parts(records: list[TrialResult]):
    agents = {(r.agent_name, r.model_id, r.prompt_version) for r in records}
    surfaces = {r.run_metadata.get("agent_surface") for r in records}
    concrete_surfaces = {surface for surface in surfaces if surface is not None}
    return agents, concrete_surfaces


def summarize(records: list[TrialResult]):
    # Missing agent_surface is compatible with a single concrete surface (legacy JSONL).
    agents, concrete_surfaces = _condition_parts(records)
    if len(agents) > 1 or len(concrete_surfaces) > 1:
        raise ValueError("Report one agent/model/prompt/input surface at a time; do not pool unlike conditions.")

    def aggregate(rows):
        times = sorted(r.duration_seconds for r in rows)
        product_rows = [r for r in rows if r.expected_kind == "product" and r.total_constraints]
        input_ok = rows and all(r.input_tokens is not None for r in rows)
        output_ok = rows and all(r.output_tokens is not None for r in rows)
        return {
            "trials": len(rows), "successful": sum(r.is_successful for r in rows),
            "success_rate": sum(r.is_successful for r in rows) / len(rows) if rows else None,
            "product_constraint_satisfaction": (
                sum(r.constraints_satisfied / r.total_constraints for r in product_rows) / len(product_rows)
                if product_rows else None),
            "termination_reasons": dict(Counter(r.termination_reason for r in rows)),
            "median_duration_seconds": median(times) if times else None,
            "p95_duration_seconds": times[math.ceil(.95 * len(times)) - 1] if times else None,
            "median_tool_calls": median(r.tool_calls for r in rows) if rows else None,
            "failure_categories": dict(Counter(failure_category(r) for r in rows if not r.is_successful)),
            "unsupported_claim_rate": None, "human_rating": None,
            "model_cost_usd": (sum(r.cost_usd for r in rows)
                               if rows and all(r.cost_usd is not None for r in rows) else None),
            "input_tokens": sum(r.input_tokens for r in rows) if input_ok else None,
            "output_tokens": sum(r.output_tokens for r in rows) if output_ok else None,
            "model_tokens": (
                sum(r.input_tokens + r.output_tokens for r in rows) if input_ok and output_ok else None),
            "token_usage_trials": sum(r.input_tokens is not None and r.output_tokens is not None for r in rows),
        }

    sample = records[0] if records else None
    surface = next(iter(concrete_surfaces), None) if concrete_surfaces else (
        sample.run_metadata.get("agent_surface") if sample else None)
    identity = {
        "agent_name": sample.agent_name if sample else None,
        "model_id": sample.model_id if sample else None,
        "prompt_version": sample.prompt_version if sample else None,
        "agent_surface": surface,
    }
    return {
        "identity": identity,
        "overall": aggregate(records),
        "by_task": {
            task: aggregate([r for r in records if r.task_id == task])
            for task in sorted({r.task_id for r in records})
        },
        "by_difficulty": {
            tier: aggregate([r for r in records if r.difficulty == tier])
            for tier in ("easy", "medium", "hard")
        },
    }


def read_records(path):
    return [TrialResult.model_validate_json(line) for line in path.read_text().splitlines() if line.strip()]


def supports_color(stream=None) -> bool:
    stream = sys.stdout if stream is None else stream
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    return hasattr(stream, "isatty") and stream.isatty()


def enable_windows_ansi() -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes

        handle = ctypes.windll.kernel32.GetStdHandle(-11)
        mode = ctypes.c_uint32()
        if ctypes.windll.kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            ctypes.windll.kernel32.SetConsoleMode(handle, mode.value | 0x0004)
    except Exception:
        pass


def failure_issue(record: TrialResult) -> str:
    if record.error:
        return record.error.splitlines()[0].strip()
    if record.termination_reason == "completed":
        return "incorrect outcome"
    return record.termination_reason.replace("_", " ")


def common_failure_issue(records: list[TrialResult]) -> tuple[str, int] | None:
    failed = [record for record in records if not record.is_successful]
    if not failed:
        return None
    issue, count = Counter(failure_issue(record) for record in failed).most_common(1)[0]
    return issue, count


def format_trial_line(record: TrialResult, *, color: bool = False) -> str:
    if record.is_successful:
        mark = f"{_GREEN}PASS{_RESET}" if color else "PASS"
        detail = ""
    else:
        mark = f"{_RED}FAIL{_RESET}" if color else "FAIL"
        issue = failure_issue(record)
        detail = f"  {_DIM}- {issue}{_RESET}" if color else f"  - {issue}"

    tier = f" [{record.difficulty}]" if record.difficulty else ""
    trial = f" #{record.trial_number}" if record.trial_number > 1 else ""
    return f"{mark}  {record.task_id}{trial}{tier}{detail}"


def format_run_summary(records: list[TrialResult], *, color: bool = False) -> str:
    if not records:
        return "No trials to report."

    lines = [format_trial_line(record, color=color) for record in records]
    passed = sum(record.is_successful for record in records)
    total = len(records)
    rate = 100.0 * passed / total
    score = f"Score: {passed}/{total} ({rate:.0f}%)"
    lines.append("")
    lines.append(f"{_BOLD}{score}{_RESET}" if color else score)

    common = common_failure_issue(records)
    if common is not None:
        issue, count = common
        failed = total - passed
        headline = f"Common failure ({count}/{failed} failed): {issue}"
        lines.append(f"{_RED}{headline}{_RESET}" if color else headline)
    elif passed == total:
        ok = "All trials passed."
        lines.append(f"{_GREEN}{ok}{_RESET}" if color else ok)

    return "\n".join(lines)


def print_trial_line(record: TrialResult, *, stream=None) -> None:
    stream = sys.stdout if stream is None else stream
    color = supports_color(stream)
    if color:
        enable_windows_ansi()
    print(format_trial_line(record, color=color), file=stream, flush=True)


def print_run_summary(records: list[TrialResult], *, stream=None, include_trials: bool = True) -> None:
    stream = sys.stdout if stream is None else stream
    color = supports_color(stream)
    if color:
        enable_windows_ansi()
    if include_trials:
        text = format_run_summary(records, color=color)
    else:
        # Live run already printed each trial; emit score + common failure only.
        passed = sum(record.is_successful for record in records)
        total = len(records)
        rate = 100.0 * passed / total if total else 0.0
        parts = [""]
        score = f"Score: {passed}/{total} ({rate:.0f}%)"
        parts.append(f"{_BOLD}{score}{_RESET}" if color else score)
        common = common_failure_issue(records)
        if common is not None:
            issue, count = common
            failed = total - passed
            headline = f"Common failure ({count}/{failed} failed): {issue}"
            parts.append(f"{_RED}{headline}{_RESET}" if color else headline)
        elif total and passed == total:
            ok = "All trials passed."
            parts.append(f"{_GREEN}{ok}{_RESET}" if color else ok)
        text = "\n".join(parts)
    print(text, file=stream, flush=True)


def markdown_report(records):
    report = summarize(records)
    identity = report["identity"]
    overall = report["overall"]
    lines = [
        "# Evaluation evidence",
        "",
        f"- Agent: `{identity['agent_name']}`",
        f"- Model: `{identity['model_id']}`",
        f"- Prompt: `{identity['prompt_version']}`",
        f"- Input surface: `{identity['agent_surface']}`",
        f"- Tokens (input/output/total): "
        f"`{overall['input_tokens']}` / `{overall['output_tokens']}` / `{overall['model_tokens']}` "
        f"across `{overall['token_usage_trials']}` measured trials",
        "",
        "| Task | Successful / trials | Median calls | Median seconds | p95 seconds |",
        "|---|---:|---:|---:|---:|",
    ]
    for task, row in report["by_task"].items():
        lines.append(
            f"| {task} | {row['successful']}/{row['trials']} | {row['median_tool_calls']} | "
            f"{row['median_duration_seconds']:.4f} | {row['p95_duration_seconds']:.4f} |"
        )
    lines.extend(["", "## By difficulty", ""])
    for tier, row in report["by_difficulty"].items():
        if not row["trials"]:
            continue
        lines.append(
            f"- **{tier}**: {row['successful']}/{row['trials']} successful; "
            f"tokens={row['model_tokens']}; failures={row['failure_categories']}"
        )
    lines.extend(["", "## Failures", ""])
    failures = [r for r in records if not r.is_successful]
    if not failures:
        lines.append("No failed trials in this run.")
    for r in failures:
        lines.append(
            f"- {r.task_id}, repetition {r.trial_number}: {failure_category(r)}; "
            f"termination={r.termination_reason}; selected={r.selected_product_ids}."
        )
    lines.extend([
        "",
        "Categories describe observed outcomes; root causes require trace inspection.",
        "Repeated trials are not independent tasks. API timings are not browser timings.",
        "Missing token/cost measurements remain null; no price estimate is invented.",
        "",
    ])
    return "\n".join(lines)
