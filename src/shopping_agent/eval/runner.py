"""Sequential, process-isolated trials with private store setup and scoring."""

import hashlib
import os
import subprocess
import multiprocessing
import platform
import random
import sys
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path
from time import monotonic

from shopping_agent.agent.agent import Agent as ClaudeAgent
from shopping_agent.agent.rules import RulesAgent
from shopping_agent.contracts import (
    CartSelection,
    CatalogExample,
    ShoppingRequest,
    TaskDefinition,
    TrialResult,
)
from shopping_agent.eval.scoring import score
from shopping_agent.interfaces import AgentInput, AgentOutput
from shopping_agent.tools.api import CatalogAPI
from shopping_agent.tools.budget import BudgetExceeded, BudgetedTools

ROOT = Path(__file__).resolve().parents[3]


def agent_input_for_task(task: TaskDefinition) -> AgentInput:
    """NL surface gets original_text only; structured keeps constraints + ranking."""
    if task.agent_surface == "nl":
        return AgentInput(
            request=ShoppingRequest(original_text=task.request.original_text),
            ranking_rule=None,
        )

    return AgentInput(
        request=task.request.model_copy(deep=True),
        ranking_rule=task.ranking_rule,
    )


def load_store_modules():
    # Mock environment remains an independently runnable repository application.
    path = str(ROOT / "mock-store")
    if path not in sys.path:
        sys.path.insert(0, path)

    from server.app import create_app
    from server.state import Store, load_examples

    return create_app, Store, load_examples


def agent_metadata(agent):
    selected, name = select_agent(agent)
    return {"agent_name": name, "model_id": getattr(selected, "model", None),
            "prompt_version": getattr(selected, "prompt_version", None)}


def metadata(max_calls: int, seconds: float) -> dict:
    source = hashlib.sha256()
    for path in sorted((ROOT / "src").rglob("*.py")):
        source.update(str(path.relative_to(ROOT)).encode())
        source.update(path.read_bytes())

    try:
        commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        commit = None
    return {
        "git_commit": commit,
        "source_sha256": source.hexdigest(),
        "runner_version": "evaluation-v2",
        "baseline_version": "rules-v1",
        "max_tool_calls": max_calls,
        "timeout_seconds": seconds,
        "python": platform.python_version(),
        "packages": {name: version(name) for name in ("fastapi", "pydantic", "httpx", "requests", "starlette")},
        "started_at": datetime.now(timezone.utc).isoformat(),
    }


def select_agent(agent=None, agent_name: str = "rules"):
    if agent is not None:
        if isinstance(agent, RulesAgent):
            return agent, "rules"
        return agent, "claude" if isinstance(agent, ClaudeAgent) else type(agent).__name__
    if agent_name == "claude":
        return ClaudeAgent(), "claude"
    if agent_name == "rules":
        return RulesAgent(), "rules"
    raise ValueError("agent_name must be rules or claude")


def claude_credentials_available(agent=None) -> bool:
    """Honor Agent(api_key=...), not only the process environment."""
    if agent is not None and isinstance(agent, ClaudeAgent):
        return bool(getattr(agent, "api_key", None))
    if agent is not None:
        # Custom agents may carry their own key; env is the fallback for named Claude.
        return True
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def validate_experiment(task: TaskDefinition | None = None, tasks: dict[str, TaskDefinition] | None = None,
                        agent=None, agent_name: str = "rules"):
    """Reject incompatible agent/surface/credentials before a trial writes output."""
    selected, name = select_agent(agent, agent_name)
    surface_tasks = list(tasks.values()) if tasks is not None else ([task] if task is not None else [])
    if name == "rules" and any(t.agent_surface == "nl" for t in surface_tasks):
        raise ValueError("Rules agent requires structured tasks; use --tasks data/tasks/harness or --agent claude.")
    if name == "claude" and not claude_credentials_available(selected):
        raise ValueError("ANTHROPIC_API_KEY is required for a live Claude benchmark; no trials were run.")
    return selected, name


def failure_record(task, trial_number, reason, duration, trace, error, config) -> TrialResult:
    return TrialResult(
        task_id=task.task_id,
        task_version=task.version,
        catalog_version=task.catalog_version,
        **config["agent"],
        trial_number=trial_number,
        mode="api",
        selected_product_ids=[],
        response_text="Trial interrupted before a final result.",
        constraints_satisfied=0,
        total_constraints=sum(c.hard for c in task.request.constraints),
        tool_calls=len(trace),
        duration_seconds=duration,
        termination_reason=reason,
        is_successful=False,
        difficulty=task.difficulty,
        expected_kind=task.expected.kind,
        tool_trace=trace,
        error=error,
        run_metadata=config,
    )


def run_trial(
    catalog: CatalogExample,
    task: TaskDefinition,
    trial_number: int = 1,
    max_calls: int = 20,
    seconds: float = 60,
    agent=None,
    on_trace=None,
) -> TrialResult:
    """Worker core; suite's parent process supplies the noncooperative deadline."""
    from starlette.testclient import TestClient

    create_app, Store, _ = load_store_modules()
    store = Store(catalog, {task.task_id: task})
    store.reset(task.task_id)
    config = metadata(max_calls, seconds)
    selected_agent, agent_name = validate_experiment(task=task, agent=agent)
    config["agent"] = agent_metadata(selected_agent)
    config["agent_surface"] = task.agent_surface
    config["task_sha256"] = hashlib.sha256(task.model_dump_json().encode()).hexdigest()
    config["catalog_sha256"] = hashlib.sha256(catalog.model_dump_json().encode()).hexdigest()

    with TestClient(create_app(store)) as client:
        tools = BudgetedTools(
            CatalogAPI(client),
            max_calls=max_calls,
            seconds=seconds,
            on_trace=on_trace,
        )
        start = monotonic()
        error = None

        try:
            output = selected_agent.run(agent_input_for_task(task), tools)
            output = AgentOutput.model_validate(output)

            if monotonic() >= tools.deadline:
                raise BudgetExceeded("timeout")

        except BudgetExceeded as exc:
            error = exc.reason
            output = AgentOutput(response_text="Trial budget exhausted.", termination_reason=exc.reason)

        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            output = AgentOutput(response_text="Trial failed.", termination_reason="unrecoverable_failure")

        duration = monotonic() - start
        snapshot = store.snapshot()
        success, satisfied, total = score(task, output, snapshot)

        return TrialResult(
            task_id=task.task_id,
            task_version=task.version,
            catalog_version=task.catalog_version,
            **agent_metadata(selected_agent),
            input_tokens=getattr(selected_agent, "input_tokens", None),
            output_tokens=getattr(selected_agent, "output_tokens", None),
            trial_number=trial_number,
            mode="api",
            selected_product_ids=output.selected_product_ids,
            response_text=output.response_text,
            evidence=output.evidence,
            claims=[claim.model_dump(mode="json") for claim in output.claims],
            cart_items=[
                CartSelection(product_id=row["product_id"], quantity=row["quantity"])
                for row in snapshot["cart"]["items"]
            ],
            constraints_satisfied=satisfied,
            total_constraints=total,
            tool_calls=len(tools.trace),
            duration_seconds=duration,
            termination_reason=output.termination_reason,
            is_successful=success,
            difficulty=task.difficulty,
            expected_kind=task.expected.kind,
            tool_trace=[event.model_dump(mode="json") for event in tools.trace],
            final_state=snapshot,
            error=error,
            run_metadata=config,
        )


def _worker(send, catalog, task, trial_number, max_calls, seconds, agent):
    try:
        send.send(("started", None))

        def on_trace(event):
            send.send(("trace", event.model_dump(mode="json")))

        result = run_trial(catalog, task, trial_number, max_calls, seconds, agent, on_trace)
        send.send(("result", result.model_dump(mode="json")))

    except Exception as exc:
        send.send(("error", f"{type(exc).__name__}: {exc}"))

    finally:
        send.close()


def isolated_trial(
    catalog: CatalogExample,
    task: TaskDefinition,
    trial_number: int = 1,
    max_calls: int = 20,
    seconds: float = 60,
    agent=None,
) -> TrialResult:
    if max_calls < 1 or seconds <= 0:
        raise ValueError("budgets must be positive")

    selected_agent, _ = validate_experiment(task=task, agent=agent)
    context = multiprocessing.get_context("spawn")
    receive, send = context.Pipe(duplex=False)
    process = context.Process(
        target=_worker,
        args=(send, catalog, task, trial_number, max_calls, seconds, selected_agent),
    )
    config = metadata(max_calls, seconds)
    config["agent"] = agent_metadata(selected_agent)
    config["agent_surface"] = task.agent_surface
    config["task_sha256"] = hashlib.sha256(task.model_dump_json().encode()).hexdigest()
    config["catalog_sha256"] = hashlib.sha256(catalog.model_dump_json().encode()).hexdigest()
    process.start()
    send.close()

    start = monotonic()
    deadline = start + 60  # Separate bounded worker-startup allowance.
    traces = {}

    try:
        while True:
            remaining = deadline - monotonic()

            if remaining <= 0 or not receive.poll(remaining):
                return failure_record(
                    task,
                    trial_number,
                    "timeout",
                    monotonic() - start,
                    list(traces.values()),
                    "Worker exceeded wall-clock budget; final state unavailable.",
                    config,
                )

            try:
                kind, payload = receive.recv()
            except EOFError:
                return failure_record(
                    task,
                    trial_number,
                    "unrecoverable_failure",
                    monotonic() - start,
                    list(traces.values()),
                    "Worker exited without a result.",
                    config,
                )

            if kind == "started":
                start = monotonic()
                deadline = start + seconds

            elif kind == "trace":
                traces[payload["sequence"]] = payload

            elif kind == "result":
                return TrialResult.model_validate(payload)

            elif kind == "error":
                return failure_record(
                    task,
                    trial_number,
                    "unrecoverable_failure",
                    monotonic() - start,
                    list(traces.values()),
                    payload,
                    config,
                )

    finally:
        if process.is_alive():
            process.terminate()

        process.join(timeout=2)

        if process.is_alive():
            process.kill()
            process.join()

        receive.close()


def run_suite(
    catalog: CatalogExample,
    tasks: dict[str, TaskDefinition],
    output: Path,
    repetitions: int = 3,
    seed: int = 498,
    max_calls: int = 20,
    seconds: float = 60,
    agent_name: str = "rules",
    on_result=None,
) -> list[TrialResult]:
    if repetitions < 1:
        raise ValueError("repetitions must be positive")

    validate_experiment(tasks=tasks, agent_name=agent_name)
    output.parent.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)
    results: list[TrialResult] = []

    # Refuse to overwrite previous experiments silently.
    with output.open("x", encoding="utf-8") as stream:
        for repetition in range(1, repetitions + 1):
            order = sorted(tasks)
            rng.shuffle(order)

            for position, task_id in enumerate(order):
                agent, _ = select_agent(agent_name=agent_name)
                result = isolated_trial(catalog, tasks[task_id], repetition, max_calls, seconds, agent)
                result.run_metadata.update(seed=seed, task_order=order, task_position=position)
                stream.write(result.model_dump_json() + "\n")
                stream.flush()
                results.append(result)
                if on_result is not None:
                    on_result(result)

    return results
