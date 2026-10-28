"""Surface B suite-v3: loader-validated expected sets and NL-only agent input."""

import pytest

from server.state import load_examples
from shopping_agent.eval.runner import agent_input_for_task
from shopping_agent.example_checks import expected_products

SURFACE_B_PRODUCT = {
    "nl_cheapest_waterproof_jacket_m": {"ridge-shell"},
    "nl_cheapest_waterproof_daypack": {"harbor-backpack"},
    "nl_size9_waterproof_shoe_by_rating": {"tarn-fell"},
    "nl_cheapest_waterproof_jacket_s": {"river-shell"},
    "nl_cheapest_waterproof_shoe_size9_under_100": {"tarn-fell"},
    "nl_cheapest_waterproof_compact_bag": {"umbra-messenger"},
    "nl_highest_rated_waterproof_jacket_m": {"summit-shell"},
    "nl_navy_waterproof_jacket_m": {"ridge-shell"},
    "nl_waterproof_30l_under_100": {"basalt-carryall"},
    "nl_black_waterproof_jacket_m": {"summit-shell"},
    "no_waterproof_pack_under_40": set(),
    "prefer_comfort_but_require_waterproof_pack": {"basalt-carryall"},
    "no_waterproof_jacket_under_50": set(),
    "no_waterproof_shoe_size10": set(),
    "prefer_rating_but_require_waterproof_bag": {"harbor-backpack"},
    "prefer_comfort_but_require_waterproof_shoe": {"tarn-fell"},
    "no_waterproof_expedition_under_100": set(),
    "price_hike_recover_to_alternative": {"summit-shell"},
    "stockout_recover_footwear": {"granite-hiker"},
    "implied_monsoon_kit_single_sku": {"harbor-backpack"},
    "mutation_then_empty": set(),
    "restock_recover_to_cinder": {"cinder-hiker"},
    "stockout_then_empty_footwear_budget": set(),
    "implied_bike_messenger_waterproof": {"umbra-messenger"},
    "comfort_pack_stockout_abstain": set(),
    "price_hike_daypack_recover_carryall": {"basalt-carryall"},
    "stockout_size_s_jacket_empty": set(),
}

CLARIFY = {
    "clarify_footwear_size": "size",
    "clarify_jacket_size_nl": "size",
    "clarify_bag_capacity": "liter",
}


def test_surface_b_counts_and_versions():
    _, tasks = load_examples()
    assert len(tasks) == 30
    assert sum(t.difficulty == "easy" for t in tasks.values()) == 10
    assert sum(t.difficulty == "medium" for t in tasks.values()) == 10
    assert sum(t.difficulty == "hard" for t in tasks.values()) == 10
    assert all(t.agent_surface == "nl" for t in tasks.values())
    assert all(t.version == "suite-v3" for t in tasks.values())


def test_surface_b_expected_sets_match_catalog_and_mutations():
    catalog, tasks = load_examples()
    assert set(SURFACE_B_PRODUCT) | set(CLARIFY) == set(tasks)
    for task_id, winners in SURFACE_B_PRODUCT.items():
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
    agent_in = agent_input_for_task(task)
    assert agent_in.request.clarification_needed is None
    assert agent_in.request.constraints == []


@pytest.mark.parametrize("task_id", list(SURFACE_B_PRODUCT) + list(CLARIFY))
def test_every_surface_b_agent_input_is_nl_only(task_id):
    _, tasks = load_examples()
    agent_in = agent_input_for_task(tasks[task_id])
    dumped = agent_in.request.model_dump()
    assert dumped["constraints"] == []
    assert dumped["preferences"] == []
    assert dumped["clarification_needed"] is None
    assert agent_in.ranking_rule is None
    assert len(dumped["original_text"]) > 20
