"""Sequential, process-isolated trials with private store setup and scoring."""

import hashlib
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


def metadata(max_calls: int, seconds: float) -> dict:
    source = hashlib.sha256()
    for path in sorted((ROOT / "src").rglob("*.py")):
        source.update(str(path.relative_to(ROOT)).encode())
        source.update(path.read_bytes())

    return {
        "source_sha256": source.hexdigest(),
        "runner_version": "pilot-v1",
        "baseline_version": "rules-v1",
        "max_tool_calls": max_calls,
        "timeout_seconds": seconds,
        "python": platform.python_version(),
        "packages": {name: version(name) for name in ("fastapi", "pydantic", "httpx")},
        "started_at": datetime.now(timezone.utc).isoformat(),
    }


def select_agent(agent=None, agent_name: str = "rules"):
    if agent is not None:
        if isinstance(agent, RulesAgent):
            return agent, "rules"
        return agent, "claude"
    if agent_name == "claude":
        return ClaudeAgent(), "claude"
    if agent_name == "rules":
        return RulesAgent(), "rules"
    raise ValueError("agent_name must be rules or claude")


def failure_record(task, trial_number, reason, duration, trace, error, config) -> TrialResult:
    return TrialResult(
        task_id=task.task_id,
        task_version=task.version,
        catalog_version=task.catalog_version,
        agent_name="rules",
        model_id=None,
        prompt_version=None,
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

    selected_agent, agent_name = select_agent(agent)

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
            agent_name=agent_name,
            model_id=None,
            prompt_version=None,
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

    context = multiprocessing.get_context("spawn")
    receive, send = context.Pipe(duplex=False)
    process = context.Process(
        target=_worker,
        args=(send, catalog, task, trial_number, max_calls, seconds, agent),
    )
    config = metadata(max_calls, seconds)
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
