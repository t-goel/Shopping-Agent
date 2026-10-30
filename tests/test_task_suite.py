"""Authoring checks for the 10-task suite-v4 NL scored suite."""

import json
from pathlib import Path

import pytest

from shopping_agent.example_checks import expected_products
from server.state import load_examples

ROOT = Path(__file__).resolve().parents[1]

SUITE_PRODUCT = {
    "nl_cheapest_waterproof_jacket_m": {"ridge-shell"},
    "nl_cheapest_waterproof_daypack": {"harbor-backpack"},
    "nl_size9_waterproof_shoe_by_rating": {"tarn-fell"},
    "prefer_comfort_but_require_waterproof_pack": {"basalt-carryall"},
    "no_waterproof_jacket_under_50": set(),
    "price_hike_recover_to_alternative": {"summit-shell"},
    "mutation_then_empty": set(),
    "restock_recover_to_cinder": {"cinder-hiker"},
    "implied_monsoon_kit_single_sku": {"harbor-backpack"},
}

CLARIFY = {
    "clarify_jacket_size_nl": "size",
}

SUITE_IDS = set(SUITE_PRODUCT) | set(CLARIFY)


def test_suite_composition_and_difficulty_mix():
    catalog, tasks = load_examples()

    assert set(tasks) == SUITE_IDS
    assert len(tasks) == 10
    assert all(task.catalog_version == catalog.version == "catalog-v2" for task in tasks.values())
    assert all(task.agent_surface == "nl" for task in tasks.values())
    assert all(task.version == "suite-v4" for task in tasks.values())

    counts = {"easy": 0, "medium": 0, "hard": 0}
    for task in tasks.values():
        counts[task.difficulty] += 1

    assert counts == {"easy": 3, "medium": 3, "hard": 4}


def test_expected_sets_recompute_from_catalog_and_mutations():
    catalog, tasks = load_examples()

    assert set(SUITE_PRODUCT) | set(CLARIFY) == set(tasks)
    for task_id, winners in SUITE_PRODUCT.items():
        task = tasks[task_id]
        assert expected_products(catalog, task) == winners
        assert set(task.expected.valid_product_ids) == winners


@pytest.mark.parametrize("task_id,needle", list(CLARIFY.items()))
def test_clarify_tasks_have_no_planted_cue(task_id, needle):
    _, tasks = load_examples()
    task = tasks[task_id]
    assert task.expected.kind == "clarification"
    assert task.request.clarification_needed is None
    assert task.expected.question_contains == needle


def test_task_summary_stays_in_sync_with_task_files():
    catalog, tasks = load_examples()
    summary = json.loads((ROOT / "docs/benchmark/task-summary.json").read_text())
    rows = {row["task_id"]: row for row in summary["tasks"]}

    assert summary["suite_version"] == "suite-v4"
    assert summary["catalog_version"] == catalog.version
    assert summary["agent_surface"] == "nl"
    assert summary["task_count"] == len(tasks) == 10
    assert summary["difficulty_counts"] == {"easy": 3, "medium": 3, "hard": 4}
    assert set(rows) == set(tasks)

    for task in tasks.values():
        row = rows[task.task_id]
        assert row["difficulty"] == task.difficulty
        assert row["expected_kind"] == task.expected.kind
        assert row["ranking_rule"] == task.ranking_rule
        assert row["mutations"] == len(task.mutations)
        assert row["axes"], task.task_id
