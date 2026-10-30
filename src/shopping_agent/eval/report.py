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


def summarize(records: list[TrialResult]):
    def aggregate(rows):
        times = sorted(r.duration_seconds for r in rows)
        product_rows = [r for r in rows if r.expected_kind == "product" and r.total_constraints]
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
            "unsupported_claim_rate": None, "human_rating": None,
            "model_cost_usd": None, "model_tokens": None,
        }
    return {"overall": aggregate(records), "by_difficulty": {
        tier: aggregate([r for r in records if r.difficulty == tier])
        for tier in ("easy", "medium", "hard")
    }}


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
