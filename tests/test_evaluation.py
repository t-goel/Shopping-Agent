import json
import time
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from server.app import create_app
from server.state import Store, load_examples
from shopping_agent.agent.rules import RulesAgent, rank
from shopping_agent.contracts import Constraint, Mutation, ProductObservation, SearchInput
from shopping_agent.eval.report import summarize
from shopping_agent.eval.runner import isolated_trial, run_trial
from shopping_agent.eval.scoring import score
from shopping_agent.interfaces import AgentInput, AgentOutput, Claim
from shopping_agent.tools.api import CatalogAPI, ToolError
from shopping_agent.tools.budget import BudgetedTools, BudgetExceeded
from shopping_agent.verifier import check_constraints, verify_claims


def observation(product):
    return ProductObservation(product=product, source_url="http://testserver/listing",
                              observed_at=datetime.now(timezone.utc), catalog_version="catalog-v2")


def test_verifier_boundary_missing_boolean_and_claims():
    catalog, _ = load_examples()
    obs = observation(catalog.products[0])
    checks = check_constraints(obs, [
        Constraint(attribute="price", operator="lte", value=89),
        Constraint(attribute="price", operator="lte", value=88.99),
        Constraint(attribute="missing", operator="eq", value=True),
        Constraint(attribute="waterproof", operator="eq", value=1),
        Constraint(attribute="size", operator="eq", value="S", hard=False),
    ])
    assert [c.status for c in checks] == ["pass", "fail", "unknown", "fail"]
    claims = [Claim(claim_id=field, product_id=obs.product.product_id, field=field, value=value)
              for field, value in [("price", 89), ("waterproof", 1), ("missing", "yes")]]
    evidence = verify_claims(obs, claims)
    assert [e.status for e in evidence] == ["supports", "contradicts", "unknown"]
    assert all(e.source_url == obs.source_url and e.observed_at == obs.observed_at for e in evidence)
    with pytest.raises(ValueError, match="IDs"):
        verify_claims(obs, [claims[0].model_copy(update={"product_id": "wrong"})])


def test_ranking_ties_ratings_and_no_reviews():
    catalog, _ = load_examples()
    a = catalog.products[0].model_copy(deep=True)
    b = a.model_copy(deep=True, update={"product_id": "a-first"})
    assert rank([observation(a), observation(b)], "lowest_price")[0].product.product_id == "a-first"
    assert rank([observation(catalog.products[4]), observation(a)], "highest_rating")[0].product == a


@pytest.mark.parametrize("task_id", [
    "cheapest_waterproof_jacket", "clarify_jacket_size", "no_waterproof_under_50",
    "price_change", "stock_change",
])
def test_existing_tasks_complete_against_live_state(task_id):
    catalog, tasks = load_examples()
    result = run_trial(catalog, tasks[task_id])
    assert result.is_successful, result.model_dump()
    assert result.tool_calls <= 10
    if task_id == "cheapest_waterproof_jacket":
        assert len(result.claims) == 2
        assert all(e.status == "supports" for e in result.evidence)
    if task_id == "clarify_jacket_size":
        assert result.tool_calls == 0
    if task_id in {"price_change", "stock_change"}:
        assert result.termination_reason == "no_valid_product"
        assert result.final_state["applied_mutations"] == [0]
        assert not result.cart_items


@pytest.mark.parametrize("change", [{"stock": 0}, {"price": 120}])
def test_mutation_recovery_selects_valid_replacement(change):
    catalog, tasks = load_examples()
    catalog = catalog.model_copy(deep=True)
    catalog.products[1].price = 95
    task = tasks["cheapest_waterproof_jacket"].model_copy(deep=True)
    task.expected.valid_product_ids = ["summit-shell"]
    task.mutations = [Mutation(after_observations=1, product_id="ridge-shell", **change)]
    result = run_trial(catalog, task)
    assert result.is_successful
    assert result.selected_product_ids == ["summit-shell"]


def test_price_drop_can_make_initial_nonmatch_the_winner():
    catalog, tasks = load_examples()
    task = tasks["cheapest_waterproof_jacket"].model_copy(deep=True)
    task.expected.valid_product_ids = ["summit-shell"]
    task.mutations = [Mutation(after_observations=1, product_id="summit-shell", price=80)]
    result = run_trial(catalog, task)
    assert result.is_successful
    assert result.selected_product_ids == ["summit-shell"]


def test_reset_isolates_cart_and_mutations():
    catalog, tasks = load_examples()
    changed = run_trial(catalog, tasks["price_change"])
    normal = run_trial(catalog, tasks["cheapest_waterproof_jacket"])
    assert changed.final_state["products"]["ridge-shell"]["price"] == 109
    assert normal.final_state["products"]["ridge-shell"]["price"] == 89
    assert len(normal.cart_items) == 1
    assert catalog.products[0].price == 89


def test_public_adapter_and_budget_record_http_errors():
    catalog, tasks = load_examples()
    with TestClient(create_app(Store(catalog, tasks))) as client:
        tools = BudgetedTools(CatalogAPI(client), max_calls=1)
        with pytest.raises(ToolError):
            tools.get_listing("missing")
        assert "404" in tools.trace[0].error
        with pytest.raises(BudgetExceeded) as exc:
            tools.inspect_cart()
        assert exc.value.reason == "max_tool_calls_exceeded"
        assert len(tools.trace) == 1


def test_cooperative_timeout_and_failure_denominator():
    catalog, tasks = load_examples()
    result = run_trial(catalog, tasks["cheapest_waterproof_jacket"], max_calls=1)
    assert not result.is_successful
    assert result.termination_reason == "max_tool_calls_exceeded"
    good = run_trial(catalog, tasks["cheapest_waterproof_jacket"])
    report = summarize([good, result])
    assert report["overall"]["success_rate"] == .5
    assert report["overall"]["product_constraint_satisfaction"] == .5
    assert report["by_difficulty"]["hard"]["success_rate"] is None
    assert report["overall"]["unsupported_claim_rate"] is None
    now = [0.0]
    tools = BudgetedTools(object(), seconds=1, clock=lambda: now[0])
    now[0] = 2
    with pytest.raises(BudgetExceeded) as exc:
        tools.inspect_cart()
    assert exc.value.reason == "timeout"


class BlockedAgent:
    def run(self, inputs, tools):
        tools.search(SearchInput(query="jackets"))
        time.sleep(30)


def test_process_deadline_stops_noncooperative_agent():
    catalog, tasks = load_examples()
    start = time.monotonic()
    result = isolated_trial(catalog, tasks["cheapest_waterproof_jacket"], seconds=1, agent=BlockedAgent())
    assert time.monotonic() - start < 10
    assert result.termination_reason == "timeout" and not result.is_successful
    assert result.tool_calls == 1
    assert result.final_state is None


class InspectInputAgent:
    def run(self, inputs, tools):
        assert set(inputs.model_dump()) == {"request", "ranking_rule"}
        assert not hasattr(inputs, "expected") and not hasattr(tools, "reset")
        assert not hasattr(tools, "snapshot")
        return RulesAgent().run(inputs, tools)


def test_agent_input_contains_no_oracle_or_controls():
    catalog, tasks = load_examples()
    assert run_trial(catalog, tasks["cheapest_waterproof_jacket"], agent=InspectInputAgent()).is_successful


def test_scorer_rejects_stale_choice_wrong_cart_and_false_abstention():
    catalog, tasks = load_examples()
    task = tasks["cheapest_waterproof_jacket"]
    store = Store(catalog, tasks)
    store.reset(task.task_id)
    output = AgentOutput(selected_product_ids=["ridge-shell"], response_text="Selected.", termination_reason="completed")
    assert not score(task, output, store.snapshot())[0]  # No cart.
    store.add_to_cart("ridge-shell", 1)
    assert score(task, output, store.snapshot())[0]
    store.products["ridge-shell"].price = 109
    assert not score(task, output, store.snapshot())[0]
    store.reset("price_change")
    abstention = AgentOutput(response_text="No match.", termination_reason="no_valid_product")
    assert not score(tasks["price_change"], abstention, store.snapshot())[0]  # Mutation not observed yet.
    store.search("jackets")
    assert score(tasks["price_change"], abstention, store.snapshot())[0]


def test_cli_generates_actual_jsonl_and_report(tmp_path):
    import os
    import subprocess
    import sys
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    output = tmp_path / "runs.jsonl"
    env = {**os.environ, "PYTHONPATH": str(root / "src")}
    command = [sys.executable, "-m", "shopping_agent.cli", "run", "--repetitions", "1", "--output", str(output)]
    completed = subprocess.run(command, cwd=root, env=env, capture_output=True, text=True, timeout=30)
    assert completed.returncode == 0, completed.stderr
    rows = [json.loads(line) for line in output.read_text().splitlines()]
    assert len(rows) == 5 and all(row["is_successful"] for row in rows)
    assert json.loads(completed.stdout)["overall"]["trials"] == 5
    again = subprocess.run(command, cwd=root, env=env, capture_output=True, text=True, timeout=30)
    assert again.returncode != 0
    assert len(output.read_text().splitlines()) == 5


@pytest.mark.parametrize("new_price", [96, 120])
def test_final_refresh_reranks_late_price_change(new_price):
    catalog, tasks = load_examples()
    catalog = catalog.model_copy(deep=True)
    catalog.products[1].price = 95
    task = tasks["cheapest_waterproof_jacket"].model_copy(deep=True)
    task.expected.valid_product_ids = ["summit-shell"]
    # Search plus five listing reads occur before the selected candidate is refreshed.
    task.mutations = [Mutation(after_observations=6, product_id="ridge-shell", price=new_price)]
    result = run_trial(catalog, task)
    assert result.is_successful
    assert result.selected_product_ids == ["summit-shell"]
    assert result.tool_calls == 9
    assert result.cart_items[0].product_id == "summit-shell"


def test_late_change_can_preserve_the_same_winner():
    catalog, tasks = load_examples()
    task = tasks["cheapest_waterproof_jacket"].model_copy(deep=True)
    task.mutations = [Mutation(after_observations=6, product_id="ridge-shell", price=90)]
    result = run_trial(catalog, task)
    assert result.is_successful
    assert result.selected_product_ids == ["ridge-shell"]
    assert result.tool_calls == 8
    assert result.claims[1]["value"] == 90
