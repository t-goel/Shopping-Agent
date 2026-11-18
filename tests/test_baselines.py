import json

import pytest

from server.state import load_examples
from shopping_agent.agent.baselines import (
    CONDITIONS,
    MODEL_ID,
    OfflineAgent,
    interpret_request,
)
from shopping_agent.eval.compare import comparison, csv_text, markdown_table
from shopping_agent.eval.runner import run_suite, run_trial, select_agent


def fixture():
    catalog, tasks = load_examples()
    return catalog, tasks


def test_interpret_request_reads_only_the_request_text():
    constraints, ranking, clarification = interpret_request(
        "Cheapest in-stock waterproof medium jacket at or under $120."
    )
    values = {(row.attribute, str(row.operator), row.value) for row in constraints}
    assert ("category", "eq", "jackets") in values
    assert ("waterproof", "eq", True) in values
    assert ("size", "eq", "M") in values
    assert ("price", "lte", 120.0) in values
    assert ranking == "lowest_price"
    assert clarification is None

    constraints, ranking, clarification = interpret_request(
        "Waterproof hiking shoes, men's US 9. If several qualify, pick the one "
        "shoppers rate highest on average."
    )
    values = {(row.attribute, str(row.operator), row.value) for row in constraints}
    assert ("category", "eq", "footwear") in values
    assert ("size", "eq", "9") in values
    assert ranking == "highest_rating_then_reviews"

    _, _, clarification = interpret_request(
        "I usually wear medium but I'm not sure this brand runs the same—figure something out."
    )
    assert clarification and "size" in clarification.casefold()


@pytest.mark.parametrize("condition", CONDITIONS)
def test_every_condition_runs_on_natural_language(condition):
    catalog, tasks = fixture()
    result = run_trial(catalog, tasks["nl_cheapest_waterproof_jacket_m"], agent=OfflineAgent(condition))
    assert result.agent_name == condition
    assert result.model_id == MODEL_ID
    assert len(result.prompt_id) == 64
    assert result.termination_reason == "completed"
    assert result.error is None
    assert result.run_metadata["baseline"] == condition
    assert result.agent_diagnostics["verification_gate"] == (condition == "full")


def test_verification_gate_is_the_difference_between_full_and_ablation():
    catalog, tasks = fixture()
    full = run_trial(catalog, tasks["nl_cheapest_waterproof_jacket_m"], agent=OfflineAgent("full"))
    ablated = run_trial(catalog, tasks["nl_cheapest_waterproof_jacket_m"], agent=OfflineAgent("no_verifier"))
    assert full.is_successful and ablated.is_successful
    assert full.selected_product_ids == ablated.selected_product_ids
    assert full.evidence and not ablated.evidence
    assert full.prompt_id != ablated.prompt_id
    assert full.tool_calls > ablated.tool_calls


def test_select_agent_accepts_all_conditions():
    for condition in CONDITIONS:
        selected, name = select_agent(agent_name=condition)
        assert isinstance(selected, OfflineAgent)
        assert name == condition
    with pytest.raises(ValueError, match="unknown condition"):
        OfflineAgent("not-a-condition")


def test_three_seeds_per_task_records_each_seed(monkeypatch, tmp_path):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    catalog, tasks = fixture()
    subset = {task_id: tasks[task_id] for task_id in list(sorted(tasks))[:2]}
    output = tmp_path / "seeds.jsonl"
    results = run_suite(catalog, subset, output, agent_name="full", seeds=[7, 8, 9])
    assert len(results) == 6
    assert sorted({result.run_metadata["seed"] for result in results}) == [7, 8, 9]
    assert [result.trial_number for result in results].count(1) == 2
    assert all(result.agent_name == "full" for result in results)
    assert output.read_text().count("\n") == 6


def test_comparison_builds_one_row_per_condition(tmp_path):
    catalog, tasks = fixture()
    subset = {task_id: tasks[task_id] for task_id in ["nl_cheapest_waterproof_jacket_m"]}
    paths = {}
    for condition in ("single_prompt", "full"):
        path = tmp_path / f"{condition}.jsonl"
        run_suite(catalog, subset, path, agent_name=condition, seeds=[3])
        paths[condition] = path

    result = comparison(paths)
    assert result["protocol"]["trials_per_condition"] == 1
    assert result["protocol"]["seeds"] == [3]
    assert result["conditions"]["single_prompt"]["successful"] == 0
    assert result["conditions"]["full"]["successful"] == 1
    assert result["conditions"]["full"]["evidence_trials"] == 1
    table = markdown_table(result)
    assert "Single-prompt LLM" in table and "verification gate" in table
    assert "Condition" in csv_text(result)

    mixed = tmp_path / "mixed.jsonl"
    lines = [json.loads(line) for line in paths["full"].read_text().splitlines()]
    lines[0]["agent_name"] = "single_prompt"
    mixed.write_text("\n".join(json.dumps(line) for line in lines) + "\n")
    with pytest.raises(ValueError, match="do not pool conditions"):
        comparison({"full": mixed})


def test_cli_compare_writes_table_and_machine_readable_artifacts(tmp_path):
    from shopping_agent.cli import main

    catalog, tasks = fixture()
    task_dir = tmp_path / "tasks"
    task_dir.mkdir()
    source = task_dir / "nl_cheapest_waterproof_jacket_m.json"
    source.write_text(
        json.dumps(json.loads(tasks["nl_cheapest_waterproof_jacket_m"].model_dump_json())),
        encoding="utf-8",
    )
    output = tmp_path / "comparison"

    assert main([
        "compare",
        "--output-dir", str(output),
        "--mode", "flat",
        "--tasks", str(task_dir),
        "--seeds", "1,2,3",
        "--conditions", "no_verifier,full",
    ]) == 0
    assert (output / "no_verifier.jsonl").exists()
    assert (output / "full.jsonl").exists()
    assert (output / "comparison.json").exists()
    assert (output / "comparison.csv").exists()
    table = (output / "table1.md").read_text(encoding="utf-8")
    assert "Table 1" in table and "Proposed agent" in table
    summary = json.loads((output / "comparison.json").read_text(encoding="utf-8"))
    assert summary["protocol"]["trials_per_condition"] == 3
