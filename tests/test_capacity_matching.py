import pytest

from shopping_agent.agent.agent import Agent
from shopping_agent.agent.request_parser import parse_request
from shopping_agent.comparison import approximate_bounds, capacity_matches, matches
from shopping_agent.contracts import Constraint, Product, ProductObservation, ShoppingRequest
from shopping_agent.interfaces import AgentInput


def test_approximate_bounds_and_capacity_matches():
    lower, upper = approximate_bounds(30.0, tolerance=5.0)
    assert lower == 25.0
    assert upper == 35.0

    assert capacity_matches(30.0, 30.0, tolerance=5.0)
    assert capacity_matches(25.0, 30.0, tolerance=5.0)
    assert capacity_matches(35.0, 30.0, tolerance=5.0)
    assert not capacity_matches(24.9, 30.0, tolerance=5.0)
    assert not capacity_matches(35.1, 30.0, tolerance=5.0)


def test_matches_with_constraint_tolerance():
    product_28l = ProductObservation(
        store_id="test-store",
        source_url="http://test.store/p/bag-28l",
        observed_at="2026-11-17T00:00:00Z",
        product=Product(
            product_id="bag-28l",
            title="28L Pack",
            description="28L Daypack",
            category="bags",
            price=50.0,
            stock=5,
            seller="TestSeller",
            attributes={"capacity_liters": 28.0},
        ),
    )
    product_36l = ProductObservation(
        store_id="test-store",
        source_url="http://test.store/p/bag-36l",
        observed_at="2026-11-17T00:00:00Z",
        product=Product(
            product_id="bag-36l",
            title="36L Pack",
            description="36L Pack",
            category="bags",
            price=50.0,
            stock=5,
            seller="TestSeller",
            attributes={"capacity_liters": 36.0},
        ),
    )

    constraint_with_tol = Constraint(
        attribute="capacity_liters",
        operator="eq",
        value=30.0,
        tolerance=5.0,
    )

    # 28L is within 30 +/- 5 (25 to 35)
    assert matches(product_28l, constraint_with_tol)
    # 36L is outside 30 +/- 5
    assert not matches(product_36l, constraint_with_tol)


def test_nl_request_approximate_capacity_interprets_realistic_bounds():
    query = "Looking for a waterproof bag, approximately 30 liters, under $100."
    req, rule = parse_request(query)

    assert any(c.attribute == "category" and c.value == "bags" for c in req.constraints)
    assert any(c.attribute == "waterproof" and c.value is True for c in req.constraints)

    capacity_constraints = [c for c in req.constraints if c.attribute == "capacity_liters"]
    assert len(capacity_constraints) == 2
    gte_c = next(c for c in capacity_constraints if c.operator.value == "gte")
    lte_c = next(c for c in capacity_constraints if c.operator.value == "lte")

    assert gte_c.value == 25.0
    assert lte_c.value == 35.0


def test_nl_daypack_interprets_realistic_bounds():
    query = "I need a waterproof daypack for a day hike under $80."
    req, rule = parse_request(query)

    assert any(c.attribute == "category" and c.value == "bags" for c in req.constraints)
    capacity_constraints = [c for c in req.constraints if c.attribute == "capacity_liters"]
    assert len(capacity_constraints) == 2
    gte_c = next(c for c in capacity_constraints if c.operator.value == "gte")
    lte_c = next(c for c in capacity_constraints if c.operator.value == "lte")
    assert gte_c.value == 20.0
    assert lte_c.value == 25.0


def test_nl_tasks_route_through_interpreter_and_log_diagnostics():
    from server.state import load_examples
    from shopping_agent.eval.runner import run_trial
    from tests.test_claude_agent import ScriptedClaude, final, search

    catalog, tasks = load_examples()
    task = tasks["prefer_comfort_but_require_waterproof_pack"]

    decision = '''{"status":"completed","product_id":"basalt-carryall",
      "response":"Basalt Carryall matches the ~30L waterproof pack requirement.",
      "constraints":[{"attribute":"category","operator":"eq","value":"bags"},
                     {"attribute":"waterproof","operator":"eq","value":true},
                     {"attribute":"capacity_liters","operator":"gte","value":25},
                     {"attribute":"capacity_liters","operator":"lte","value":35}],
      "ranking_rule":"lowest_price","claims":[{"field":"capacity_liters","value":30}]}'''

    agent = ScriptedClaude([search("bags"), final(decision)])
    result = run_trial(catalog, task, agent=agent)

    assert result.is_successful
    assert result.selected_product_ids == ["basalt-carryall"]
    # Verify diagnostics contain extracted constraints from the query interpreter
    extracted = result.agent_diagnostics.get("extracted_constraints", [])
    assert len(extracted) >= 3
    assert any(c["attribute"] == "category" and c["value"] == "bags" for c in extracted)
    assert any(c["attribute"] == "waterproof" and c["value"] is True for c in extracted)
    assert any(c["attribute"] == "capacity_liters" and c["operator"] == "gte" and c["value"] == 25.0 for c in extracted)
    assert any(c["attribute"] == "capacity_liters" and c["operator"] == "lte" and c["value"] == 35.0 for c in extracted)
    assert result.agent_diagnostics.get("interpreted_ranking_rule") == "none"


def test_structured_tasks_do_not_re_interpret():
    from shopping_agent.contracts import ShoppingRequest
    from tests.test_claude_agent import ScriptedClaude, final, search

    agent = ScriptedClaude([final('{"status":"no_valid_product","response":"No items found."}')])
    structured_input = AgentInput(
        request=ShoppingRequest(
            original_text="some text that could be re-interpreted differently",
            constraints=[
                Constraint(attribute="category", operator="eq", value="jackets", hard=True),
                Constraint(attribute="price", operator="lte", value=50.0, hard=True),
            ],
            preferences=[],
        ),
        ranking_rule="lowest_price",
    )

    class MockTools:
        pass

    output = agent.run(structured_input, MockTools())
    # Should use the supplied structured constraints, not re-interpret
    assert output.diagnostics["extracted_constraints"] == [
        {"attribute": "category", "operator": "eq", "value": "jackets", "hard": True},
        {"attribute": "price", "operator": "lte", "value": 50.0, "hard": True},
    ]
    assert output.diagnostics["interpreted_ranking_rule"] == "lowest_price"
