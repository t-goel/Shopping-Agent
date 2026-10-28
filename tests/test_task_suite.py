"""Authoring checks for the full 15-task suite; evaluator-only, agent-independent."""

import json
from pathlib import Path

import pytest

from shopping_agent.example_checks import expected_products
from shopping_agent.eval.runner import run_trial
from server.state import load_examples

ROOT = Path(__file__).resolve().parents[1]

PILOT_IDS = {
    "cheapest_waterproof_jacket", "clarify_jacket_size", "no_waterproof_under_50",
    "price_change", "stock_change",
}

SUITE_IDS = PILOT_IDS | {
    "cheapest_waterproof_bag", "clarify_shoe_size", "highest_rated_waterproof_shoe",
    "comfy_waterproof_bag", "jacket_title_trap", "sponsored_shoe_search",
    "no_big_waterproof_bag", "top_rated_waterproof_bag", "duffel_price_drop",
    "stock_replenished_shoe",
}

TERMINATION_FOR_KIND = {
    "product": "completed",
    "no_valid_product": "no_valid_product",
    "clarification": "clarification_needed",
}


def test_suite_composition_and_difficulty_mix():
    catalog, tasks = load_examples()

    assert set(tasks) == SUITE_IDS
    assert all(task.catalog_version == catalog.version == "catalog-v2" for task in tasks.values())

    counts = {"easy": 0, "medium": 0, "hard": 0}
    for task in tasks.values():
        counts[task.difficulty] += 1

    assert counts == {"easy": 3, "medium": 8, "hard": 4}


def test_expected_sets_recompute_from_catalog_and_mutations():
    catalog, tasks = load_examples()

    for task in tasks.values():
        if task.expected.kind == "clarification":
            assert task.request.clarification_needed and task.expected.question_contains
            continue

        assert expected_products(catalog, task) == set(task.expected.valid_product_ids), task.task_id


def test_task_summary_stays_in_sync_with_task_files():
    catalog, tasks = load_examples()
    summary = json.loads((ROOT / "docs/benchmark/task-summary.json").read_text())
    rows = {row["task_id"]: row for row in summary["tasks"]}

    assert summary["catalog_version"] == catalog.version
    assert summary["task_count"] == len(tasks) == 15
    assert set(rows) == set(tasks)

    for task in tasks.values():
        row = rows[task.task_id]
        assert row["difficulty"] == task.difficulty
        assert row["expected_kind"] == task.expected.kind
        assert row["ranking_rule"] == task.ranking_rule
        assert row["mutations"] == len(task.mutations)
        assert row["axes"], task.task_id


# The deterministic baseline needs one read per product in the searched category
# plus re-verification; bags (9 products) is the largest at 11 calls, so 20 leaves
# recovery behavior possible without making the budget the challenge.
@pytest.mark.parametrize("task_id", sorted(SUITE_IDS - PILOT_IDS))
def test_rules_baseline_solves_every_new_task_within_budget(task_id):
    catalog, tasks = load_examples()
    result = run_trial(catalog, tasks[task_id], max_calls=20)

    assert result.is_successful, result.model_dump()
    assert result.termination_reason == TERMINATION_FOR_KIND[tasks[task_id].expected.kind]
    assert result.tool_calls <= 13


def test_ranking_rules_produce_different_winners_over_same_candidates():
    catalog, tasks = load_examples()

    # Footwear size-9 waterproof candidates tie on rating; price and rating rules disagree.
    assert tasks["highest_rated_waterproof_shoe"].expected.valid_product_ids == [
        "granite-hiker", "tarn-fell"
    ]
    assert tasks["sponsored_shoe_search"].expected.valid_product_ids == ["tarn-fell"]
