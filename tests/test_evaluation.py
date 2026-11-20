import json
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from server.app import create_app
from server.state import Store, load_examples
from shopping_agent.agent.baselines import OfflineAgent
from shopping_agent.agent.rules import RulesAgent, rank
from shopping_agent.contracts import Constraint, Mutation, ProductObservation, SearchInput
from shopping_agent.eval.metrics import claim_audit
from shopping_agent.eval.report import summarize
from shopping_agent.eval.runner import agent_input_for_task, isolated_trial, run_trial
from shopping_agent.eval.scoring import score
from shopping_agent.interfaces import AgentInput, AgentOutput, Claim
from shopping_agent.tools.api import CatalogAPI, ToolError
from shopping_agent.tools.budget import BudgetedTools, BudgetExceeded, verification_scope
from shopping_agent.verifier import (
    check_constraints,
    verification_failure_reason,
    verify_claims,
)

HARNESS = Path(__file__).resolve().parents[1] / "data" / "tasks" / "harness"


def harness_examples():
    return load_examples(tasks_path=HARNESS)


def observation(product):
    return ProductObservation(product=product, source_url="http://testserver/listing",
                              observed_at=datetime.now(timezone.utc))


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


def test_verification_failure_reason_names_failed_field_and_observed_value():
    catalog, _ = load_examples()
    obs = observation(catalog.products[0])  # ridge-shell: $89, waterproof, in stock

    reason = verification_failure_reason(obs, [
        Constraint(attribute="price", operator="lte", value=80),
        Constraint(attribute="waterproof", operator="eq", value=True),
    ])
    assert "price" in reason and "fail" in reason and "89.0" in reason
    assert "waterproof" not in reason

    out_of_stock = obs.model_copy(deep=True)
    out_of_stock.product.stock = 0
    assert "stock is 0" in verification_failure_reason(out_of_stock, [])


def test_ranking_ties_ratings_and_no_reviews():
    catalog, _ = load_examples()
    a = catalog.products[0].model_copy(deep=True)
    b = a.model_copy(deep=True, update={"product_id": "a-first"})
    assert rank([observation(a), observation(b)], "lowest_price")[0].product.product_id == "a-first"
    assert rank([observation(catalog.products[4]), observation(a)], "highest_rating")[0].product == a


def test_rating_then_reviews_breaks_average_ties():
    catalog, tasks = load_examples()
    task = tasks["nl_size9_waterproof_shoe_by_rating"]
    from shopping_agent.example_checks import expected_products
    assert expected_products(catalog, task) == {"tarn-fell"}


@pytest.mark.parametrize("task_id", [
    "cheapest_waterproof_jacket", "clarify_jacket_size", "no_waterproof_under_50",
    "price_change", "stock_change",
])
def test_harness_tasks_complete_against_live_state(task_id):
    catalog, tasks = harness_examples()
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





def test_rules_agent_cannot_solve_nl_surface_without_cheat_sheet():
    catalog, tasks = load_examples()
    with pytest.raises(ValueError, match="structured tasks"):
        run_trial(catalog, tasks["nl_cheapest_waterproof_jacket_m"])


def test_nl_agent_input_strips_constraints_ranking_and_planted_clarify():
    _, tasks = load_examples()
    product_task = tasks["prefer_comfort_but_require_waterproof_pack"]
    clarify_task = tasks["clarify_jacket_size_nl"]

    product_input = agent_input_for_task(product_task)
    assert product_input.ranking_rule is None
    assert product_input.request.constraints == []
    assert product_input.request.preferences == []
    assert product_input.request.clarification_needed is None
    assert "waterproof" in product_input.request.original_text.casefold()

    clarify_input = agent_input_for_task(clarify_task)
    assert clarify_input.request.clarification_needed is None
    assert clarify_task.expected.question_contains == "size"


@pytest.mark.parametrize("change", [{"stock": 0}, {"price": 120}])
def test_mutation_recovery_selects_valid_replacement(change):
    catalog, tasks = harness_examples()
    catalog = catalog.model_copy(deep=True)
    catalog.products[1].price = 95
    task = tasks["cheapest_waterproof_jacket"].model_copy(deep=True)
    task.expected.valid_product_ids = ["summit-shell"]
    task.mutations = [Mutation(after_observations=1, product_id="ridge-shell", **change)]
    result = run_trial(catalog, task)
    assert result.is_successful
    assert result.selected_product_ids == ["summit-shell"]


def test_price_drop_can_make_initial_nonmatch_the_winner():
    catalog, tasks = harness_examples()
    task = tasks["cheapest_waterproof_jacket"].model_copy(deep=True)
    task.expected.valid_product_ids = ["summit-shell"]
    task.mutations = [Mutation(after_observations=1, product_id="summit-shell", price=80)]
    result = run_trial(catalog, task)
    assert result.is_successful
    assert result.selected_product_ids == ["summit-shell"]


def test_reset_isolates_cart_and_mutations():
    catalog, tasks = harness_examples()
    changed = run_trial(catalog, tasks["price_change"])
    normal = run_trial(catalog, tasks["cheapest_waterproof_jacket"])
    assert changed.final_state["products"]["ridge-shell"]["price"] == 109
    assert normal.final_state["products"]["ridge-shell"]["price"] == 89
    assert len(normal.cart_items) == 1
    assert catalog.products[0].price == 89


def test_public_adapter_and_budget_record_http_errors():
    catalog, tasks = harness_examples()
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
    catalog, tasks = harness_examples()
    result = run_trial(catalog, tasks["cheapest_waterproof_jacket"], max_calls=1)
    assert not result.is_successful
    assert result.termination_reason == "max_tool_calls_exceeded"
    good = run_trial(catalog, tasks["cheapest_waterproof_jacket"])
    report = summarize([good, result])
    assert report["overall"]["success_rate"] == .5
    assert report["overall"]["product_constraint_satisfaction"] == .5
    assert report["by_difficulty"]["hard"]["success_rate"] is None
    # The completed trial declares checkable claims; the aborted trial declares none.
    assert report["overall"]["unsupported_claim_rate"] == 0
    assert report["overall"]["assessable_claims"] > 0
    assert report["by_task"]["cheapest_waterproof_jacket"]["unsupported_claim_rate"] == 0
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
    catalog, tasks = harness_examples()
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
    catalog, tasks = harness_examples()
    assert run_trial(catalog, tasks["cheapest_waterproof_jacket"], agent=InspectInputAgent()).is_successful


def test_scorer_rejects_stale_choice_wrong_cart_and_false_abstention():
    catalog, tasks = harness_examples()
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
    root = Path(__file__).resolve().parents[1]
    output = tmp_path / "runs.jsonl"
    env = {**os.environ, "PYTHONPATH": str(root / "src"), "NO_COLOR": "1"}
    command = [
        sys.executable, "-m", "shopping_agent.cli", "run",
        "--mode", "flat",
        "--repetitions", "1",
        "--tasks", str(root / "data" / "tasks" / "harness"),
        "--output", str(output),
    ]
    completed = subprocess.run(command, cwd=root, env=env, capture_output=True, text=True, timeout=30)
    assert completed.returncode == 0, completed.stderr
    rows = [json.loads(line) for line in output.read_text().splitlines()]
    assert len(rows) == 5 and all(row["is_successful"] for row in rows)
    assert completed.stdout.count("PASS") == 5
    assert "Score: 5/5 (100%)" in completed.stdout
    assert "All trials passed." in completed.stdout
    json_command = [
        sys.executable, "-m", "shopping_agent.cli", "run",
        "--mode", "flat",
        "--repetitions", "1",
        "--tasks", str(root / "data" / "tasks" / "harness"),
        "--output", str(tmp_path / "runs-json.jsonl"),
        "--json",
    ]
    json_run = subprocess.run(
        json_command, cwd=root, env=env, capture_output=True, text=True, timeout=30,
    )
    assert json_run.returncode == 0, json_run.stderr
    assert json.loads(json_run.stdout)["overall"]["trials"] == 5
    again = subprocess.run(command, cwd=root, env=env, capture_output=True, text=True, timeout=30)
    assert again.returncode != 0
    assert len(output.read_text().splitlines()) == 5


@pytest.mark.parametrize("new_price", [96, 120])
def test_final_refresh_reranks_late_price_change(new_price):
    catalog, tasks = harness_examples()
    catalog = catalog.model_copy(deep=True)
    catalog.products[1].price = 95
    task = tasks["cheapest_waterproof_jacket"].model_copy(deep=True)
    task.expected.valid_product_ids = ["summit-shell"]
    # Search plus five listing reads occur before the selected candidate is refreshed.
    task.mutations = [Mutation(after_observations=6, product_id="ridge-shell", price=new_price)]
    result = run_trial(catalog, task)
    assert result.is_successful
    assert result.selected_product_ids == ["summit-shell"]
    assert result.tool_calls == 10  # list_stores probe + search + listing reads + cart
    assert result.cart_items[0].product_id == "summit-shell"


def test_late_change_can_preserve_the_same_winner():
    catalog, tasks = harness_examples()
    task = tasks["cheapest_waterproof_jacket"].model_copy(deep=True)
    task.mutations = [Mutation(after_observations=6, product_id="ridge-shell", price=90)]
    result = run_trial(catalog, task)
    assert result.is_successful
    assert result.selected_product_ids == ["ridge-shell"]
    assert result.tool_calls == 9  # list_stores probe + search + listing reads + cart
    assert result.claims[1]["value"] == 90


def test_verification_calls_are_labelled_and_charged_once():
    """The gate's reads and purchase are one budget charge each, not double counted."""
    catalog, tasks = harness_examples()
    gated = run_trial(catalog, tasks["cheapest_waterproof_jacket"], agent=OfflineAgent("full"))
    assert gated.is_successful, gated.model_dump()
    purposes = [row["purpose"] for row in gated.tool_trace]
    # The gate refresh, its empty-cart check, and the purchase it verifies.
    assert purposes.count("verification") == 3
    assert len(gated.tool_trace) == gated.tool_calls
    assert sum(summarize([gated])["overall"]["tool_calls_by_purpose"].values()) == gated.tool_calls

    ablated = run_trial(catalog, tasks["cheapest_waterproof_jacket"], agent=OfflineAgent("no_verifier"))
    assert ablated.is_successful, ablated.model_dump()
    assert {row["purpose"] for row in ablated.tool_trace} == {"agent"}
    # The gate costs exactly two calls more than the ablation of the same run.
    assert gated.tool_calls == ablated.tool_calls + 2


def test_tool_budget_charges_gate_calls_against_the_same_limit():
    catalog, tasks = harness_examples()
    with TestClient(create_app(Store(catalog, tasks))) as client:
        tools = BudgetedTools(CatalogAPI(client), max_calls=2)
        with verification_scope(tools):
            tools.get_listing("ridge-shell")
        tools.search(SearchInput(query="jackets"))
        with pytest.raises(BudgetExceeded) as exc:
            tools.inspect_cart()
        assert exc.value.reason == "max_tool_calls_exceeded"
        assert [row.purpose for row in tools.trace] == ["verification", "agent"]


def test_verification_scope_is_a_noop_for_tools_without_attribution():
    """A plain ShoppingTools still works inside the scope; it just keeps the default."""
    with verification_scope(object()):
        pass
    with verification_scope(object(), enabled=False):
        pass


def test_agent_input_copies_keep_each_trial_independent():
    _, tasks = harness_examples()
    task = tasks["cheapest_waterproof_jacket"]
    before = task.model_dump_json()
    first = agent_input_for_task(task)
    second = agent_input_for_task(task)
    assert first.request is not second.request
    first.request.constraints.clear()
    first.request.original_text = "mutated"
    assert second.request.constraints == task.request.constraints
    assert task.model_dump_json() == before


def test_each_trial_reads_its_own_copy_of_the_catalog():
    catalog, tasks = harness_examples()
    before = catalog.model_dump_json()
    changed = run_trial(catalog, tasks["price_change"])
    normal = run_trial(catalog, tasks["cheapest_waterproof_jacket"])
    assert changed.final_state["products"]["ridge-shell"]["price"] == 109
    assert normal.final_state["products"]["ridge-shell"]["price"] == 89
    assert catalog.model_dump_json() == before


def test_unsupported_claim_rate_follows_structured_claims_only():
    catalog, tasks = harness_examples()
    record = run_trial(catalog, tasks["cheapest_waterproof_jacket"])
    assert record.claims  # The rules agent declares title and price.

    contradicted = record.model_copy(deep=True)
    contradicted.claims = [{**claim, "value": 40.0} if claim["field"] == "price" else claim
                           for claim in record.claims]
    report = summarize([contradicted])["overall"]
    assert report["structured_claims"]["contradicts"] == 1
    assert report["structured_claims"]["supports"] == 1
    assert report["unsupported_claim_rate"] == 0.5
    # The explanation prose is unchanged and still truthful, so the advisory rate stays 0.
    assert report["prose_claim_contradiction_rate"] == 0

    no_claims = record.model_copy(deep=True)
    no_claims.claims = []
    quiet = summarize([no_claims])["overall"]
    assert quiet["unsupported_claim_rate"] is None
    assert quiet["assessable_claims"] == 0


def test_claims_are_audited_against_the_listing_the_trial_used():
    """Multi-store snapshots keep price on the listing, not on the product row."""
    from server.multi_store import load_multi_store_examples

    ingest, tasks = load_multi_store_examples()
    record = run_trial(ingest, tasks["multistore_cheapest_waterproof_shell"])
    assert record.is_successful, record.model_dump()
    assert record.claims  # The rules agent declares title and price.

    # The winning listing's price, not a sibling store's and not the product row.
    listing_id = record.selected_listing_ids[0]
    assert record.final_state["listings"][listing_id]["price"] == 89
    audit = claim_audit(record)
    statuses = {row["field"]: row["status"] for row in audit}
    assert statuses == {"title": "supports", "price": "supports"}
    assert {row["observed_value"] for row in audit if row["field"] == "price"} == {89}

    report = summarize([record])["overall"]
    assert report["assessable_claims"] == 2
    assert report["unsupported_claim_rate"] == 0


def test_claim_against_an_ambiguous_product_without_a_used_listing_stays_unknown():
    """An unfilled claim cannot borrow a sibling store's row."""
    from server.multi_store import load_multi_store_examples

    ingest, tasks = load_multi_store_examples()
    record = run_trial(ingest, tasks["multistore_cheapest_waterproof_shell"])
    compared = record.model_copy(deep=True)
    compared.selected_listing_ids = []
    compared.cart_items = []
    compared.claims = [row for row in record.claims if row["field"] == "price"]
    # Three stores list this product, so no single listing backs the claim.
    listed_in = [key for key, row in compared.final_state["listings"].items()
                 if row["product_id"] == "ridge-shell"]
    assert len(listed_in) == 3
    assert claim_audit(compared)[0]["status"] == "unknown"
    assert summarize([compared])["overall"]["unsupported_claim_rate"] is None
