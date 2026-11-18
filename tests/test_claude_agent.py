import pytest
from pydantic import ValidationError

from shopping_agent.agent.agent import Agent
from shopping_agent.contracts import ClaudeAnswer


def test_claude_answer_requires_product_for_completed_status():
    with pytest.raises(ValidationError, match="product_id"):
        ClaudeAnswer.model_validate({"status": "completed"})


def test_claude_answer_accepts_typed_claims():
    answer = ClaudeAnswer.model_validate({
        "status": "completed",
        "product_id": "ridge-shell",
        "claims": [{"field": "price", "value": 89}],
        "response": "Selected the shell.",
    })

    assert answer.claims[0].field == "price"
    assert answer.claims[0].value == 89


def test_agent_rejects_non_json_model_output():
    with pytest.raises(RuntimeError, match="invalid shopping JSON"):
        Agent(api_key="test").read_answer([{"type": "text", "text": "not json"}])
"""Provider-free checks of Claude's final-decision boundary."""

import json

from server.state import load_examples
from shopping_agent.agent.agent import Agent
from shopping_agent.contracts import Mutation
from shopping_agent.eval.runner import run_trial


class ScriptedClaude(Agent):
    def __init__(self, answers, max_turns=10):
        super().__init__(api_key="test-key", max_turns=max_turns)
        self.answers = iter(answers)
        self.messages_seen = []

    def ask_claude(self, messages):
        self.messages_seen.append(json.loads(json.dumps(messages)))
        return next(self.answers)


def verification_observation(messages_seen):
    """Return the most recent verification_failure observation sent into the loop."""
    found = None
    for messages in messages_seen:
        for message in messages:
            content = message.get("content")
            if not isinstance(content, str) or not content.startswith("{"):
                continue
            try:
                payload = json.loads(content)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict) and payload.get("type") == "verification_failure":
                found = payload
    return found


def final(text, reason="end_turn"):
    return {"stop_reason": reason, "content": [{"type": "text", "text": text}]}


def search(query, store_id=None):
    payload = {"query": query, "max_results": 50}
    if store_id is not None:
        payload["store_id"] = store_id
    return {"stop_reason": "tool_use", "content": [{
        "type": "tool_use", "id": "search-1", "name": "search", "input": payload,
    }]}


def list_stores():
    return {"stop_reason": "tool_use", "content": [{
        "type": "tool_use", "id": "stores-1", "name": "list_stores", "input": {},
    }]}


def test_invalid_final_response_retries_once_and_preserves_diagnostics():
    catalog, tasks = load_examples()
    agent = ScriptedClaude([final("", "max_tokens"), final("still not JSON")])
    result = run_trial(catalog, tasks["nl_cheapest_waterproof_jacket_m"], agent=agent)
    assert not result.is_successful
    assert result.termination_reason == "unrecoverable_failure"
    assert "stop_reason='end_turn'" in result.error
    assert "final_text='still not JSON'" in result.error


def test_empty_final_response_can_recover_with_one_json_correction():
    catalog, tasks = load_examples()
    agent = ScriptedClaude([
        final("", "max_tokens"),
        final('{"status":"clarification_needed","product_id":"","response":"What jacket size do you need?"}'),
    ])
    result = run_trial(catalog, tasks["clarify_jacket_size_nl"], agent=agent)
    assert result.is_successful, result.model_dump()
    assert result.termination_reason == "clarification_needed"
    assert result.response_text == "What jacket size do you need?"


def test_price_hike_keeps_claude_pick_when_still_valid():
    catalog, tasks = load_examples()
    decision = '''{"status":"completed","product_id":"summit-shell",
      "response":"Summit Shell is the cheapest waterproof M after the hike.",
      "constraints":[{"attribute":"category","operator":"eq","value":"jackets"},
                     {"attribute":"waterproof","operator":"eq","value":true},
                     {"attribute":"size","operator":"eq","value":"M"},
                     {"attribute":"price","operator":"lte","value":120}],
      "ranking_rule":"lowest_price","claims":[{"field":"price","value":96}]}'''
    result = run_trial(catalog, tasks["price_hike_recover_to_alternative"],
                       agent=ScriptedClaude([search("jackets"), final(decision)]))
    assert result.is_successful, result.model_dump()
    assert result.selected_product_ids == ["summit-shell"]
    assert result.response_text.startswith("Summit Shell")


def test_wrong_completed_pick_is_not_replaced_by_re_rank():
    """The gate reports the failure; it never silently substitutes a runner-up."""
    catalog, tasks = load_examples()
    decision = '''{"status":"completed","product_id":"city-windbreaker",
      "response":"Choose the windbreaker.",
      "constraints":[{"attribute":"category","operator":"eq","value":"jackets"},
                     {"attribute":"waterproof","operator":"eq","value":true},
                     {"attribute":"size","operator":"eq","value":"M"},
                     {"attribute":"price","operator":"lte","value":120}],
      "ranking_rule":"lowest_price","claims":[]}'''
    abstain = '''{"status":"no_valid_product","product_id":"",
      "response":"No eligible replacement.",
      "constraints":[{"attribute":"category","operator":"eq","value":"jackets"},
                     {"attribute":"waterproof","operator":"eq","value":true},
                     {"attribute":"size","operator":"eq","value":"M"},
                     {"attribute":"price","operator":"lte","value":120}],
      "ranking_rule":"lowest_price","claims":[]}'''
    agent = ScriptedClaude([search("jackets"), final(decision), final(abstain)])
    result = run_trial(catalog, tasks["price_hike_recover_to_alternative"], agent=agent)
    assert not result.is_successful
    assert result.termination_reason == "no_valid_product"
    assert result.selected_product_ids == []
    assert not result.cart_items
    assert result.response_text == "No eligible replacement."
    observation = verification_observation(agent.messages_seen)
    assert observation["rejected_product_id"] == "city-windbreaker"
    assert "waterproof" in observation["reason"]
    rejection = result.agent_diagnostics["verification_rejections"][0]
    assert rejection["product_id"] == "city-windbreaker"
    assert "recovered_after_rejection" not in result.agent_diagnostics


def test_false_abstention_is_honored_not_overridden():
    catalog, tasks = load_examples()
    decision = '''{"status":"no_valid_product","product_id":"", "response":"No match.",
      "constraints":[{"attribute":"category","operator":"eq","value":"footwear"},
                     {"attribute":"waterproof","operator":"eq","value":true},
                     {"attribute":"size","operator":"eq","value":"9"}],
      "ranking_rule":"highest_rating_then_reviews","claims":[]}'''
    result = run_trial(catalog, tasks["nl_size9_waterproof_shoe_by_rating"],
                       agent=ScriptedClaude([search("footwear"), final(decision)]))
    assert not result.is_successful
    assert result.termination_reason == "no_valid_product"
    assert result.selected_product_ids == []
    assert result.response_text == "No match."


def test_clarification_from_natural_language():
    catalog, tasks = load_examples()
    result = run_trial(catalog, tasks["clarify_jacket_size_nl"], agent=ScriptedClaude([
        final('{"status":"clarification_needed","product_id":"","response":"What jacket size do you need?"}')
    ]))
    assert result.is_successful, result.model_dump()
    assert result.tool_calls == 0
    assert result.agent_diagnostics["model_status"] == "clarification_needed"


def test_invalid_operator_gets_one_correction_turn():
    catalog, tasks = load_examples()
    bad = '''{"status":"no_valid_product","product_id":"","response":"No match",
      "constraints":[{"attribute":"category","operator":"eq","value":"jackets"},
                     {"attribute":"waterproof","operator":"eq","value":true},
                     {"attribute":"price","operator":"lt","value":50}],
      "ranking_rule":"none"}'''
    good = bad.replace('"lt"', '"lte"')
    result = run_trial(catalog, tasks["no_waterproof_jacket_under_50"],
                       agent=ScriptedClaude([search("jackets"), final(bad), final(good)]))
    assert result.is_successful, result.model_dump()
    assert result.termination_reason == "no_valid_product"


def test_completed_pick_with_coerced_constraint_types():
    catalog, tasks = load_examples()
    decision = '''{"status":"completed","product_id":"tarn-fell","response":"Tarn Fell fits.",
      "constraints":[{"attribute":"category","operator":"eq","value":"footwear"},
                     {"attribute":"waterproof","operator":"eq","value":"true"},
                     {"attribute":"size","operator":"eq","value":"9"}],
      "ranking_rule":"highest_rating_then_reviews","claims":[{"field":"price","value":128}]}'''
    result = run_trial(catalog, tasks["nl_size9_waterproof_shoe_by_rating"],
                       agent=ScriptedClaude([search("footwear"), final(decision)]))
    assert result.is_successful, result.model_dump()
    assert result.selected_product_ids == ["tarn-fell"]
    assert result.agent_diagnostics["interpreted_constraints"][1]["value"] is True


def test_model_budget_omission_is_not_silently_injected():
    catalog, tasks = load_examples()
    decision = '''{"status":"completed","product_id":"headwater-duffel","response":"Choose it",
      "constraints":[{"attribute":"category","operator":"eq","value":"bags"},
                     {"attribute":"waterproof","operator":"eq","value":true}],
      "ranking_rule":"lowest_price"}'''
    result = run_trial(catalog, tasks["implied_monsoon_kit_single_sku"],
                       agent=ScriptedClaude([search("bags"), final(decision)]))
    # Without injecting the omitted budget, Claude's pick stands and scoring fails.
    assert result.selected_product_ids == ["headwater-duffel"]
    assert result.response_text == "Choose it"
    assert not result.is_successful


def test_clarification_is_not_nudged_into_a_purchase():
    catalog, tasks = load_examples()
    clarification = '''{"status":"clarification_needed","product_id":"",
      "response":"Which matters more, capacity or waterproofing?"}'''
    result = run_trial(catalog, tasks["prefer_comfort_but_require_waterproof_pack"],
                       agent=ScriptedClaude([search("bags"), final(clarification)]))
    assert not result.is_successful
    assert result.termination_reason == "clarification_needed"
    assert result.response_text.startswith("Which matters more")
    assert not result.cart_items


def test_search_limit_is_bounded_to_public_tool_schema():
    catalog, tasks = load_examples()
    decision = '''{"status":"completed","product_id":"tarn-fell","response":"Choose it",
      "constraints":[{"attribute":"category","operator":"eq","value":"footwear"},
                     {"attribute":"waterproof","operator":"eq","value":true},
                     {"attribute":"size","operator":"eq","value":"9"}],
      "ranking_rule":"highest_rating_then_reviews"}'''
    oversized = search("footwear")
    oversized["content"][0]["input"]["max_results"] = 100
    result = run_trial(catalog, tasks["nl_size9_waterproof_shoe_by_rating"],
                       agent=ScriptedClaude([oversized, final(decision)]))
    assert result.is_successful, result.model_dump()
    assert result.tool_trace[0]["inputs"]["max_results"] == 50


def test_completed_decision_keeps_claude_response_text():
    catalog, tasks = load_examples()
    decision = '''{"status":"completed","product_id":"basalt-carryall",
      "response":"Basalt Carryall matches the ~30L waterproof need.",
      "constraints":[{"attribute":"category","operator":"eq","value":"bags"},
                     {"attribute":"waterproof","operator":"eq","value":true},
                     {"attribute":"capacity_liters","operator":"eq","value":30}],
      "ranking_rule":"lowest_price","claims":[{"field":"capacity_liters","value":30}]}'''
    result = run_trial(catalog, tasks["prefer_comfort_but_require_waterproof_pack"],
                       agent=ScriptedClaude([search("bags"), final(decision)]))
    assert result.is_successful, result.model_dump()
    assert result.selected_product_ids == ["basalt-carryall"]
    assert result.response_text == "Basalt Carryall matches the ~30L waterproof need."


def test_multi_store_claude_search_requires_store_id_and_carts_listing():
    from server.multi_store import load_multi_store_examples

    ingest, tasks = load_multi_store_examples()
    decision = '''{"status":"completed","product_id":"ridge-shell",
      "listing_id":"trailworks-direct:ridge-shell","store_id":"trailworks-direct",
      "response":"Trailworks Ridge Shell is the cheapest waterproof shell.",
      "constraints":[{"attribute":"category","operator":"eq","value":"jackets"},
                     {"attribute":"waterproof","operator":"eq","value":true}],
      "ranking_rule":"lowest_price","claims":[{"field":"price","value":89}]}'''
    agent = ScriptedClaude([
        list_stores(),
        search("jackets", store_id="trailworks-direct"),
        final(decision),
    ])
    result = run_trial(ingest, tasks["multistore_cheapest_waterproof_shell"], agent=agent)
    assert result.is_successful, result.model_dump()
    assert result.selected_product_ids == ["ridge-shell"]
    assert result.selected_listing_ids == ["trailworks-direct:ridge-shell"]
    assert result.tool_trace[0]["name"] == "list_stores"
    assert result.tool_trace[1]["inputs"]["store_id"] == "trailworks-direct"


def test_multi_store_claude_passes_listing_id_in_product_id():
    from server.multi_store import load_multi_store_examples

    ingest, tasks = load_multi_store_examples()
    # Claude passes listing_id in product_id field without explicit listing_id/store_id
    decision = '''{"status":"completed","product_id":"trailworks-direct:ridge-shell",
      "response":"Trailworks Ridge Shell is the cheapest waterproof shell.",
      "constraints":[{"attribute":"category","operator":"eq","value":"jackets"},
                     {"attribute":"waterproof","operator":"eq","value":true}],
      "ranking_rule":"lowest_price","claims":[{"field":"price","value":89}]}'''
    agent = ScriptedClaude([
        list_stores(),
        search("jackets", store_id="trailworks-direct"),
        final(decision),
    ])
    result = run_trial(ingest, tasks["multistore_cheapest_waterproof_shell"], agent=agent)
    assert result.is_successful, result.model_dump()
    assert result.selected_product_ids == ["ridge-shell"]
    assert result.selected_listing_ids == ["trailworks-direct:ridge-shell"]


def test_multi_store_claude_passes_listing_id_only():
    from server.multi_store import load_multi_store_examples

    ingest, tasks = load_multi_store_examples()
    # Claude passes listing_id only with empty product_id
    decision = '''{"status":"completed","product_id":"",
      "listing_id":"trailworks-direct:ridge-shell",
      "response":"Trailworks Ridge Shell is the cheapest waterproof shell.",
      "constraints":[{"attribute":"category","operator":"eq","value":"jackets"},
                     {"attribute":"waterproof","operator":"eq","value":true}],
      "ranking_rule":"lowest_price","claims":[{"field":"price","value":89}]}'''
    agent = ScriptedClaude([
        list_stores(),
        search("jackets", store_id="trailworks-direct"),
        final(decision),
    ])
    result = run_trial(ingest, tasks["multistore_cheapest_waterproof_shell"], agent=agent)
    assert result.is_successful, result.model_dump()
    assert result.selected_product_ids == ["ridge-shell"]
    assert result.selected_listing_ids == ["trailworks-direct:ridge-shell"]


def test_multi_store_claude_uses_get_listing_with_inverted_params():
    from server.multi_store import load_multi_store_examples

    ingest, tasks = load_multi_store_examples()
    decision = '''{"status":"completed","product_id":"ridge-shell",
      "listing_id":"trailworks-direct:ridge-shell","store_id":"trailworks-direct",
      "response":"Trailworks Ridge Shell is the cheapest waterproof shell.",
      "constraints":[{"attribute":"category","operator":"eq","value":"jackets"},
                     {"attribute":"waterproof","operator":"eq","value":true}],
      "ranking_rule":"lowest_price","claims":[{"field":"price","value":89}]}'''
    get_listing_inverted = {
        "role": "assistant",
        "content": [
            {
                "type": "tool_use",
                "id": "tool_call_gl",
                "name": "get_listing",
                "input": {"product_id": "trailworks-direct:ridge-shell"},
            }
        ],
    }
    agent = ScriptedClaude([
        list_stores(),
        search("jackets", store_id="trailworks-direct"),
        get_listing_inverted,
        final(decision),
    ])
    result = run_trial(ingest, tasks["multistore_cheapest_waterproof_shell"], agent=agent)
    assert result.is_successful, result.model_dump()
    assert result.selected_product_ids == ["ridge-shell"]
    assert result.selected_listing_ids == ["trailworks-direct:ridge-shell"]


JACKET_CONSTRAINTS = [
    {"attribute": "category", "operator": "eq", "value": "jackets"},
    {"attribute": "waterproof", "operator": "eq", "value": True},
    {"attribute": "size", "operator": "eq", "value": "M"},
    {"attribute": "price", "operator": "lte", "value": 120},
]


def jacket_decision(product_id, response, price):
    return json.dumps({
        "status": "completed",
        "product_id": product_id,
        "response": response,
        "constraints": JACKET_CONSTRAINTS,
        "ranking_rule": "lowest_price",
        "claims": [{"field": "price", "value": price}],
    })


def test_price_hike_rejection_feeds_back_and_agent_recovers_within_budget():
    catalog, tasks = load_examples()
    stale = jacket_decision("ridge-shell", "Ridge Shell is under budget.", 89)
    runner_up = jacket_decision(
        "summit-shell", "Summit Shell is cheapest after the price change.", 96,
    )
    agent = ScriptedClaude([search("jackets"), final(stale), final(runner_up)])
    result = run_trial(catalog, tasks["price_hike_recover_to_alternative"], agent=agent)

    assert result.is_successful, result.model_dump()
    assert result.termination_reason == "completed"
    assert result.selected_product_ids == ["summit-shell"]
    assert result.response_text.startswith("Summit Shell")
    assert result.cart_items[0].product_id == "summit-shell"

    observation = verification_observation(agent.messages_seen)
    assert observation["rejected_product_id"] == "ridge-shell"
    assert "price" in observation["reason"] and "120" in observation["reason"]
    assert observation["observed_price"] == 130.0
    assert observation["observed_stock"] > 0
    assert any(row["product_id"] == "summit-shell" for row in observation["observed_candidates"])
    assert observation["turns_remaining"] == 8

    diagnostics = result.agent_diagnostics
    assert diagnostics["recovered_after_rejection"] is True
    assert len(diagnostics["verification_rejections"]) == 1
    assert diagnostics["verification_rejections"][0]["product_id"] == "ridge-shell"
    assert result.tool_calls <= 20  # recovery stayed inside the public tool budget


def test_stock_drop_rejection_feeds_back_and_agent_recovers_within_budget():
    catalog, tasks = load_examples()
    task = tasks["price_hike_recover_to_alternative"].model_copy(deep=True)
    task.mutations = [Mutation(after_observations=1, product_id="ridge-shell", stock=0)]

    stale = jacket_decision("ridge-shell", "Ridge Shell is in stock.", 89)
    runner_up = jacket_decision(
        "summit-shell", "Summit Shell is still available.", 96,
    )
    agent = ScriptedClaude([search("jackets"), final(stale), final(runner_up)])
    result = run_trial(catalog, task, agent=agent)

    assert result.is_successful, result.model_dump()
    assert result.selected_product_ids == ["summit-shell"]
    assert result.cart_items[0].product_id == "summit-shell"

    observation = verification_observation(agent.messages_seen)
    assert observation["rejected_product_id"] == "ridge-shell"
    assert "stock is 0" in observation["reason"]
    assert observation["observed_stock"] == 0
    assert result.agent_diagnostics["recovered_after_rejection"] is True
    assert result.tool_calls <= 20


def test_repeated_gate_rejections_exhaust_budget_and_abstain():
    catalog, tasks = load_examples()
    stale = jacket_decision("ridge-shell", "Ridge Shell is under budget.", 89)
    agent = ScriptedClaude([search("jackets"), final(stale), final(stale)], max_turns=3)
    result = run_trial(catalog, tasks["price_hike_recover_to_alternative"], agent=agent)

    assert not result.is_successful
    assert result.termination_reason == "no_valid_product"
    assert result.selected_product_ids == []
    assert not result.cart_items
    assert result.agent_diagnostics["recovery_exhausted"] is True
    assert len(result.agent_diagnostics["verification_rejections"]) == 2
    assert "verification" in result.response_text
    assert not result.agent_diagnostics.get("recovered_after_rejection")

    observation = verification_observation(agent.messages_seen)
    assert observation["rejected_product_id"] == "ridge-shell"
    assert observation["turns_remaining"] == 1
