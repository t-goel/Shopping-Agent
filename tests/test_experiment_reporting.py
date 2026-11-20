import json
import time
from pathlib import Path

import pytest

from server.state import load_examples
from shopping_agent.agent.agent import Agent
from shopping_agent.contracts import TrialResult
from shopping_agent.eval.report import failure_category, markdown_report, summarize
from shopping_agent.eval.runner import (
    isolated_trial,
    metadata,
    model_turns_for_tool_budget,
    run_suite,
    run_trial,
    select_agent,
)


def fixture():
    root = Path(__file__).resolve().parents[1]
    catalog, tasks = load_examples(tasks_path=root / "data/tasks/harness")
    return catalog, tasks["cheapest_waterproof_jacket"]


class SlowClaude(Agent):
    def run(self, inputs, tools):
        time.sleep(30)


class BrokenClaude(Agent):
    def run(self, inputs, tools):
        raise ValueError("invalid model output")


def test_timeout_preserves_claude_identity_without_secrets():
    catalog, task = fixture()
    result = isolated_trial(catalog, task, seconds=1,
                            agent=SlowClaude(api_key="test-secret", model="test-model"))
    assert result.agent_name == "claude"
    assert result.model_id == "test-model"
    assert len(result.prompt_id) == 64
    assert result.termination_reason == "timeout"
    assert result.input_tokens is None
    assert "test-secret" not in result.model_dump_json()
    assert result.run_metadata["agent_surface"] == "structured"
    assert len(result.run_metadata["catalog_sha256"]) == 64


def test_error_preserves_model_and_failure_denominator():
    catalog, task = fixture()
    result = run_trial(catalog, task, agent=BrokenClaude(api_key="test", model="test-model"))
    assert result.model_id == "test-model"
    assert not result.is_successful
    assert summarize([result])["overall"]["success_rate"] == 0
    assert failure_category(result) == "unrecoverable_failure"


def test_real_agent_loop_with_stubbed_http_records_usage(monkeypatch):
    catalog, task = fixture()
    answers = iter([
        {"stop_reason": "tool_use", "usage": {"input_tokens": 100, "output_tokens": 20},
         "content": [{"type": "tool_use", "id": "tool-1", "name": "search",
                      "input": {"query": "jackets"}}]},
        {"stop_reason": "end_turn", "usage": {"input_tokens": 200, "output_tokens": 30},
         "content": [{"type": "text", "text": json.dumps({"status": "completed",
                      "product_id": "ridge-shell", "response": "Selected jacket."})}]},
    ])

    class Response:
        status_code = 200
        def json(self):
            return next(answers)

    monkeypatch.setattr("shopping_agent.agent.agent.requests.post", lambda *a, **kw: Response())
    result = run_trial(catalog, task, agent=Agent(api_key="test", model="stubbed-model"))
    assert result.is_successful
    assert (result.input_tokens, result.output_tokens) == (300, 50)
    assert result.model_id == "stubbed-model"
    assert summarize([result])["overall"]["model_tokens"] == 350
    assert result.cost_usd is None


def test_preflight_rejects_invalid_experiments_before_writing(tmp_path, monkeypatch):
    catalog, tasks = load_examples()
    output = tmp_path / "trials.jsonl"
    with pytest.raises(ValueError, match="structured tasks"):
        run_suite(catalog, tasks, output)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(ValueError, match="no trials were run"):
        run_suite(catalog, tasks, output, agent_name="claude")
    nl_task = next(task for task in tasks.values() if task.agent_surface == "nl")
    with pytest.raises(ValueError, match="structured tasks"):
        run_trial(catalog, nl_task)
    # Constructor-supplied keys satisfy preflight even when the env var is unset.
    result = isolated_trial(
        catalog, nl_task, seconds=1,
        agent=SlowClaude(api_key="test-secret", model="test-model"),
    )
    assert result.agent_name == "claude"
    assert result.termination_reason == "timeout"
    assert not output.exists()


def test_missing_provider_usage_is_not_reported_as_complete(monkeypatch):
    answers = iter([{"usage": {"input_tokens": 10, "output_tokens": 2}},
                    {"usage": {"output_tokens": 3}},
                    {"usage": {"input_tokens": 20, "output_tokens": 4}}])
    class Response:
        status_code = 200
        def json(self):
            return next(answers)
    monkeypatch.setattr("shopping_agent.agent.agent.requests.post", lambda *a, **kw: Response())
    agent = Agent(api_key="test")
    for _ in range(3):
        agent.ask_claude([])
    assert agent.input_tokens is None
    assert agent.output_tokens == 9


def test_per_task_report_partial_usage_and_mixed_conditions():
    catalog, task = fixture()
    good = run_trial(catalog, task)
    bad = run_trial(catalog, task, max_calls=1)
    report = summarize([good, bad])
    assert report["identity"]["agent_name"] == "rules"
    assert report["identity"]["prompt_id"] == good.prompt_id
    assert report["by_task"][task.task_id]["successful"] == 1
    assert report["by_difficulty"][task.difficulty]["trials"] == 2
    assert report["overall"]["failure_categories"] == {"max_tool_calls_exceeded": 1}
    markdown = markdown_report([good, bad])
    assert "1/2" in markdown and "Agent:" in markdown and "Prompt:" in markdown
    measured = good.model_copy(update={"input_tokens": 10, "output_tokens": 5})
    partial = summarize([measured, bad])["overall"]
    assert partial["model_tokens"] is None
    assert partial["input_tokens"] is None
    assert partial["token_usage_trials"] == 1
    other = good.model_copy(update={"agent_name": "claude", "model_id": "different"})
    with pytest.raises(ValueError, match="do not pool"):
        summarize([good, other])
    legacy = good.model_copy(update={"run_metadata": {**good.run_metadata, "agent_surface": None}})
    assert summarize([good, legacy])["identity"]["agent_surface"] == "structured"


def test_model_turn_budget_is_derived_from_tool_calls_and_overridable():
    assert model_turns_for_tool_budget(20) == 21
    assert metadata(20, 60, "claude")["max_model_turns"] == 21
    assert metadata(20, 60, "claude", 3)["max_model_turns"] == 3

    derived, name = select_agent(agent_name="claude", max_turns=21)
    assert name == "claude" and derived.max_turns == 21
    override, _ = select_agent(agent_name="claude", max_turns=3)
    assert override.max_turns == 3
    # A caller-supplied agent keeps its own explicit turn budget.
    supplied, _ = select_agent(agent=override)
    assert supplied is override and supplied.max_turns == 3


def test_run_suite_records_model_turn_budget_in_metadata(tmp_path):
    root = Path(__file__).resolve().parents[1]
    catalog, tasks = load_examples(tasks_path=root / "data/tasks/harness")
    derived = tmp_path / "derived.jsonl"
    run_suite(catalog, tasks, derived, repetitions=1, max_calls=7)
    row = json.loads(derived.read_text().splitlines()[0])
    record = TrialResult.model_validate_json(derived.read_text().splitlines()[0])
    assert row["run_metadata"]["max_tool_calls"] == 7
    assert row["run_metadata"]["max_model_turns"] == 8
    assert summarize([record])["overall"]["max_model_turns"] == 8


def test_cli_max_turns_override_is_respected(tmp_path):
    import os
    import subprocess
    import sys

    root = Path(__file__).resolve().parents[1]
    env = {**os.environ, "PYTHONPATH": str(root / "src"), "NO_COLOR": "1"}
    base = [
        sys.executable, "-m", "shopping_agent.cli", "run",
        "--mode", "flat", "--repetitions", "1",
        "--tasks", str(root / "data/tasks/harness"),
        "--max-calls", "7",
    ]
    derived_path = tmp_path / "cli-derived.jsonl"
    completed = subprocess.run(
        [*base, "--output", str(derived_path)],
        cwd=root, env=env, capture_output=True, text=True, timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    row = json.loads(derived_path.read_text().splitlines()[0])
    assert row["run_metadata"]["max_model_turns"] == 8

    override_path = tmp_path / "cli-override.jsonl"
    completed = subprocess.run(
        [*base, "--max-turns", "3", "--output", str(override_path)],
        cwd=root, env=env, capture_output=True, text=True, timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    row = json.loads(override_path.read_text().splitlines()[0])
    assert row["run_metadata"]["max_model_turns"] == 3


def test_failure_category_uses_expected_kind():
    catalog, task = fixture()
    product_abstain = run_trial(catalog, task).model_copy(update={
        "is_successful": False, "termination_reason": "no_valid_product",
        "selected_product_ids": [], "error": None, "constraints_satisfied": 0,
    })
    assert failure_category(product_abstain) == "incorrect_abstention"
    no_match = product_abstain.model_copy(update={"expected_kind": "no_match"})
    assert failure_category(no_match) == "abstention_mismatch"
    clarify = product_abstain.model_copy(update={
        "termination_reason": "clarification_needed", "expected_kind": "product",
        "constraints_satisfied": 0, "total_constraints": 3,
    })
    assert failure_category(clarify) == "unexpected_clarification"


def test_markdown_cli(tmp_path):
    import os
    import subprocess
    import sys
    catalog, task = fixture()
    record = run_trial(catalog, task)
    path = tmp_path / "trials.jsonl"
    path.write_text(record.model_dump_json() + "\n")
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run([sys.executable, "-m", "shopping_agent.cli", "report", str(path), "--markdown"],
                            env={**os.environ, "PYTHONPATH": str(root / "src")},
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert "| Task |" in result.stdout and "1/1" in result.stdout
