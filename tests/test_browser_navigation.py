"""Browser transport checks; scripted decisions test plumbing, not model reasoning."""
import json
from pathlib import Path
from time import sleep

import pytest

pytest.importorskip("playwright.sync_api")

from playwright.sync_api import Error
from server.app import create_app
from server.multi_store import MultiStore, load_multi_store_examples
from server.state import Store, load_examples
from shopping_agent.agent.agent import Agent
from shopping_agent.contracts import CartSelection, SearchInput
from shopping_agent.eval.report import summarize
from shopping_agent.eval.runner import isolated_trial, run_trial
from shopping_agent.tools.api import ToolError
from shopping_agent.tools.browser import browser_session, require_browser

pytestmark = pytest.mark.browser
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module", autouse=True)
def browser_available():
    try:
        require_browser()
    except ValueError as exc:
        pytest.skip(str(exc))


@pytest.mark.parametrize("task_id", [
    "multistore_cheapest_waterproof_shell", "multistore_cheapest_size9_waterproof_hiker",
    "multistore_cheapest_harbor_backpack", "multistore_avoid_clearance_reseller_shell",
])
def test_multi_store_rules_trial_through_ui(task_id, tmp_path):
    catalog, tasks = load_multi_store_examples()
    result = run_trial(catalog, tasks[task_id], transport="browser", artifact_dir=tmp_path)
    assert result.is_successful, result.model_dump()
    assert result.mode == "browser"
    assert result.selected_listing_ids
    assert result.browser_action_count > result.tool_calls
    assert result.run_metadata["frontend_sha256"]
    assert (tmp_path / "trace.zip").is_file()
    assert (tmp_path / "final.png").is_file()
    with pytest.raises(ValueError, match="transport"):
        summarize([result, result.model_copy(update={"mode": "api"})])


@pytest.mark.parametrize("task_id", ["cheapest_waterproof_jacket", "clarify_jacket_size", "no_waterproof_under_50", "price_change", "stock_change"])
def test_flat_harness_outcomes_through_ui(task_id, tmp_path):
    catalog, tasks = load_examples(tasks_path=ROOT / "data/tasks/harness")
    result = run_trial(catalog, tasks[task_id], transport="browser", artifact_dir=tmp_path)
    assert result.is_successful, result.model_dump()
    assert result.mode == "browser"


class ScriptedClaude(Agent):
    def __init__(self, category, product_id, status):
        super().__init__(api_key="test-key")
        self.responses = iter([
            {"stop_reason": "tool_use", "content": [{"type": "tool_use", "id": "stores", "name": "list_stores", "input": {}}]},
            {"stop_reason": "tool_use", "content": [{"type": "tool_use", "id": "search", "name": "search", "input": {"query": category, "max_results": 50}}]},
            {"stop_reason": "end_turn", "content": [{"type": "text", "text": json.dumps({
                "status": status, "product_id": product_id,
                "response": "What size do you need?" if status == "clarification_needed" else "Scripted fixture decision.",
                "constraints": [{"attribute": "category", "operator": "eq", "value": category}],
                "ranking_rule": "none",
            })}]},
        ])

    def ask_claude(self, messages):
        return next(self.responses)


# Fixture outputs are declared here, never passed via the agent's benchmark input.
@pytest.mark.parametrize("task_id,category,winner,status", [
    ("nl_cheapest_waterproof_jacket_m", "jackets", "ridge-shell", "completed"),
    ("nl_cheapest_waterproof_daypack", "bags", "harbor-backpack", "completed"),
    ("nl_size9_waterproof_shoe_by_rating", "footwear", "tarn-fell", "completed"),
    ("prefer_comfort_but_require_waterproof_pack", "bags", "basalt-carryall", "completed"),
    ("no_waterproof_jacket_under_50", "jackets", "", "no_valid_product"),
    ("clarify_jacket_size_nl", "jackets", "", "clarification_needed"),
    ("price_hike_recover_to_alternative", "jackets", "summit-shell", "completed"),
    ("mutation_then_empty", "jackets", "", "no_valid_product"),
    ("restock_recover_to_cinder", "footwear", "cinder-hiker", "completed"),
    ("implied_monsoon_kit_single_sku", "bags", "harbor-backpack", "completed"),
])
def test_claude_path_on_flat_suite_with_scripted_provider(task_id, category, winner, status, tmp_path):
    catalog, tasks = load_examples()
    result = run_trial(catalog, tasks[task_id], agent=ScriptedClaude(category, winner, status),
                       transport="browser", artifact_dir=tmp_path)
    assert result.is_successful, result.model_dump()
    assert result.agent_name == "claude"


def test_duplicate_product_store_identity_quantity_and_errors(tmp_path):
    ingest, tasks = load_multi_store_examples()
    store = MultiStore(ingest, tasks)
    with browser_session(create_app(store), tmp_path) as tools:
        directory = tools.list_stores()
        assert len(directory) == 5
        assert all("current listings" in entry.notes for entry in directory)
        assert all("Chrome only" not in entry.notes for entry in directory)
        a = tools.get_listing(listing_id="trailworks-direct:ridge-shell")
        b = tools.get_listing(listing_id="summit-outfitters:ridge-shell")
        assert a.product.price != b.product.price
        tools.add_to_cart(CartSelection(product_id="ridge-shell", listing_id=a.listing_id, quantity=2))
        cart = tools.add_to_cart(CartSelection(product_id="ridge-shell", listing_id=b.listing_id, quantity=1))
        assert {row.listing_id for row in cart.items} == {a.listing_id, b.listing_id}
        assert cart.total == a.product.price * 2 + b.product.price
        assert len(store.snapshot()["cart"]["items"]) == 2
        assert tools.search(SearchInput(query="nonexistentword", store_id="trailworks-direct")).items == []
        with pytest.raises(ToolError, match="not found"):
            tools.get_listing(listing_id="trailworks-direct:missing")
        store.listings["trailworks-direct:tarn-fell"].stock = 0  # evaluator-owned change
        with pytest.raises(ToolError, match="unavailable"):
            tools.add_to_cart(CartSelection(product_id="tarn-fell", listing_id="trailworks-direct:tarn-fell", quantity=1))


@pytest.mark.parametrize("path", ["/internal/state", "/%69nternal/reset", "/api/products", "https://example.com"])
def test_browser_cannot_navigate_to_private_api_or_other_origins(path, tmp_path):
    catalog, tasks = load_examples()
    with browser_session(create_app(Store(catalog, tasks)), tmp_path) as tools:
        with pytest.raises(Error):
            tools.page.goto(path if path.startswith("http") else tools.base_url + path)


class BlockedBrowserAgent:
    def run(self, inputs, tools):
        tools.search(SearchInput(query="jackets"))
        sleep(30)


def test_hard_browser_timeout_retains_actions_and_mode(tmp_path):
    catalog, tasks = load_examples(tasks_path=ROOT / "data/tasks/harness")
    result = isolated_trial(catalog, tasks["cheapest_waterproof_jacket"], agent=BlockedBrowserAgent(),
                            transport="browser", seconds=1, artifact_dir=tmp_path)
    assert result.termination_reason == "timeout"
    assert not result.is_successful and result.final_state is None
    assert result.mode == "browser" and result.browser_actions
    assert (tmp_path / "actions.json").is_file()


def test_logical_call_budget_is_enforced_in_browser_mode(tmp_path):
    catalog, tasks = load_examples(tasks_path=ROOT / "data/tasks/harness")
    result = run_trial(catalog, tasks["cheapest_waterproof_jacket"], transport="browser",
                       max_calls=1, artifact_dir=tmp_path)
    assert result.termination_reason == "max_tool_calls_exceeded"
    assert not result.is_successful and result.tool_calls == 1


def test_stale_cart_rejection_is_visible_and_recoverable(tmp_path):
    catalog, tasks = load_examples()
    store = Store(catalog, tasks)
    with browser_session(create_app(store), tmp_path) as tools:
        tools.get_listing("ridge-shell")
        store.products["ridge-shell"].stock = 0  # change after the page was rendered
        with pytest.raises(ToolError, match="insufficient stock") as caught:
            tools._ui("click", tools.page.get_by_role("button", name="Add selected listing to bag", exact=True), fetch=True)
        assert caught.value.status_code == 409
        assert any(event["error"] for event in tools.actions)
        assert tools.get_listing("summit-shell").product.stock > 0
        assert not tools.inspect_cart().items
