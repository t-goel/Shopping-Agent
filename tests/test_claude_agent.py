"""Provider-free checks of Claude's final-decision boundary."""

from server.state import load_examples
from shopping_agent.agent.agent import Agent
from shopping_agent.eval.runner import run_trial


class ScriptedClaude(Agent):
    def __init__(self, answers):
        super().__init__(api_key="test-key")
        self.answers = iter(answers)

    def ask_claude(self, messages):
        return next(self.answers)


def final(text, reason="end_turn"):
    return {"stop_reason": reason, "content": [{"type": "text", "text": text}]}


def search(query):
    return {"stop_reason": "tool_use", "content": [{
        "type": "tool_use", "id": "search-1", "name": "search", "input": {"query": query, "max_results": 50},
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


def test_price_hike_rechecks_all_candidates_and_rejects_wrong_model_pick():
    catalog, tasks = load_examples()
    decision = '''{"status":"completed","product_id":"city-windbreaker",
      "response":"Choose the cheapest waterproof size M jacket.",
      "constraints":[{"attribute":"category","operator":"eq","value":"jackets"},
                     {"attribute":"waterproof","operator":"eq","value":true},
                     {"attribute":"size","operator":"eq","value":"M"},
                     {"attribute":"price","operator":"lte","value":120}],
      "ranking_rule":"lowest_price","claims":[]}'''
    result = run_trial(catalog, tasks["price_hike_recover_to_alternative"],
                       agent=ScriptedClaude([search("jackets"), final(decision)]))
    assert result.is_successful, result.model_dump()
    assert result.selected_product_ids == ["summit-shell"]
    assert result.cart_items[0].product_id == "summit-shell"


def test_rating_rule_can_correct_false_abstention():
    catalog, tasks = load_examples()
    decision = '''{"status":"no_valid_product","product_id":"", "response":"No match.",
      "constraints":[{"attribute":"category","operator":"eq","value":"footwear"},
                     {"attribute":"waterproof","operator":"eq","value":true},
                     {"attribute":"size","operator":"eq","value":"9"}],
      "ranking_rule":"highest_rating_then_reviews","claims":[]}'''
    result = run_trial(catalog, tasks["nl_size9_waterproof_shoe_by_rating"],
                       agent=ScriptedClaude([search("footwear"), final(decision)]))
    assert result.is_successful, result.model_dump()
    assert result.selected_product_ids == ["tarn-fell"]


def test_clarification_from_natural_language():
    catalog, tasks = load_examples()
    result = run_trial(catalog, tasks["clarify_jacket_size_nl"], agent=ScriptedClaude([
        final('{"status":"clarification_needed","product_id":"","response":"What jacket size do you need?"}')
    ]))
    assert result.is_successful, result.model_dump()
    assert result.tool_calls == 0


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


def test_empty_search_recovers_from_public_broad_search():
    catalog, tasks = load_examples()
    decision = '''{"status":"no_valid_product","product_id":"","response":"No match",
      "constraints":[{"attribute":"category","operator":"eq","value":"footwear"},
                     {"attribute":"waterproof","operator":"eq","value":"true"},
                     {"attribute":"stock","operator":"gte","value":"1"},
                     {"attribute":"size","operator":"eq","value":9}],
      "ranking_rule":"highest_rating_then_reviews"}'''
    result = run_trial(catalog, tasks["nl_size9_waterproof_shoe_by_rating"],
                       agent=ScriptedClaude([search("hiking shoes men waterproof"), final(decision)]))
    assert result.is_successful, result.model_dump()
    assert result.selected_product_ids == ["tarn-fell"]
    assert result.agent_diagnostics["interpreted_constraints"][1]["value"] is True


def test_stated_budget_survives_model_omission():
    catalog, tasks = load_examples()
    decision = '''{"status":"completed","product_id":"headwater-duffel","response":"Choose it",
      "constraints":[{"attribute":"category","operator":"eq","value":"bags"},
                     {"attribute":"waterproof","operator":"eq","value":true}],
      "ranking_rule":"lowest_price"}'''
    result = run_trial(catalog, tasks["implied_monsoon_kit_single_sku"],
                       agent=ScriptedClaude([search("bags"), final(decision)]))
    assert result.is_successful, result.model_dump()
    assert result.selected_product_ids == ["harbor-backpack"]


def test_fit_uncertainty_prevents_cart_even_if_model_picks_jacket():
    catalog, tasks = load_examples()
    decision = '''{"status":"completed","product_id":"ridge-shell","response":"Choose it",
      "constraints":[{"attribute":"category","operator":"eq","value":"jackets"}],
      "ranking_rule":"lowest_price"}'''
    result = run_trial(catalog, tasks["clarify_jacket_size_nl"],
                       agent=ScriptedClaude([search("jackets"), final(decision)]))
    assert result.is_successful, result.model_dump()
    assert result.termination_reason == "clarification_needed"
    assert not result.cart_items


def test_approximate_capacity_gets_one_reconsideration_turn():
    catalog, tasks = load_examples()
    clarification = '''{"status":"clarification_needed","product_id":"",
      "response":"Which matters more, capacity or waterproofing?"}'''
    selection = '''{"status":"completed","product_id":"basalt-carryall","response":"Choose it",
      "constraints":[{"attribute":"category","operator":"eq","value":"bags"},
                     {"attribute":"waterproof","operator":"eq","value":true},
                     {"attribute":"capacity_liters","operator":"eq","value":30}],
      "ranking_rule":"lowest_price"}'''
    result = run_trial(catalog, tasks["prefer_comfort_but_require_waterproof_pack"],
                       agent=ScriptedClaude([search("bags"), final(clarification), final(selection)]))
    assert result.is_successful, result.model_dump()
    assert result.selected_product_ids == ["basalt-carryall"]


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


def test_approximate_capacity_is_checked_even_if_model_omits_it():
    catalog, tasks = load_examples()
    decision = '''{"status":"completed","product_id":"harbor-backpack","response":"Choose it",
      "constraints":[{"attribute":"category","operator":"eq","value":"bags"},
                     {"attribute":"waterproof","operator":"eq","value":true}],
      "ranking_rule":"lowest_price"}'''
    result = run_trial(catalog, tasks["prefer_comfort_but_require_waterproof_pack"],
                       agent=ScriptedClaude([search("bags"), final(decision)]))
    assert result.is_successful, result.model_dump()
    assert result.selected_product_ids == ["basalt-carryall"]


def test_repeated_unnecessary_capacity_clarification_uses_observed_candidates():
    catalog, tasks = load_examples()
    clarification = '''{"status":"clarification_needed","product_id":"",
      "response":"Which matters more, capacity or comfort?"}'''
    result = run_trial(catalog, tasks["prefer_comfort_but_require_waterproof_pack"],
                       agent=ScriptedClaude([search("bags"), final(clarification), final(clarification)]))
    assert result.is_successful, result.model_dump()
    assert result.selected_product_ids == ["basalt-carryall"]
    assert result.agent_diagnostics["eligible_product_ids"] == ["basalt-carryall"]
