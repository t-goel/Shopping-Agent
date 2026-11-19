"""Tests for alias/coercion layer, dead repair branch fix, and prompt auditing."""

import json
from unittest.mock import MagicMock

import pytest

from server.state import load_examples
from shopping_agent.agent.agent import (
    INTERPRETATION_PROMPT,
    PROMPT,
    Agent,
    VerificationRejection,
)
from shopping_agent.comparison import canonicalize_size, coerce_numeric, matches
from shopping_agent.contracts import (
    Constraint,
    Operator,
    Product,
    ProductObservation,
    ShoppingRequest,
)
from shopping_agent.interfaces import AgentInput
from shopping_agent.verifier import eligible, field_value
from tests.test_claude_agent import ScriptedClaude, final, search


def _make_obs(product_id: str, category: str, size=None, price=50.0, waterproof=True, stock=5, capacity_liters=None):
    attrs = {"waterproof": waterproof}
    if size is not None:
        attrs["size"] = size
    if capacity_liters is not None:
        attrs["capacity_liters"] = capacity_liters
    return ProductObservation(
        store_id="store-1",
        source_url=f"http://test.store/p/{product_id}",
        observed_at="2026-11-18T00:00:00Z",
        product=Product(
            product_id=product_id,
            title=f"Test {product_id}",
            description=f"Description for {product_id}",
            category=category,
            price=price,
            stock=stock,
            seller="Seller",
            attributes=attrs,
        ),
    )


def test_canonicalize_size():
    assert canonicalize_size("medium") == "M"
    assert canonicalize_size("Medium") == "M"
    assert canonicalize_size("small") == "S"
    assert canonicalize_size("S") == "S"
    assert canonicalize_size("large") == "L"
    assert canonicalize_size("extra large") == "XL"
    assert canonicalize_size("extra-large") == "XL"
    assert canonicalize_size("extra small") == "XS"
    assert canonicalize_size(9) == "9"
    assert canonicalize_size("9") == "9"
    assert canonicalize_size(9.0) == "9"
    assert canonicalize_size(9.5) == "9.5"
    assert canonicalize_size("US 9 men's") == "9"
    assert canonicalize_size("US 9 mens") == "9"
    assert canonicalize_size("Men's US 9") == "9"
    assert canonicalize_size("Men's 9") == "9"
    assert canonicalize_size("Women's 8.5") == "8.5"
    assert canonicalize_size("size 9") == "9"
    assert canonicalize_size("10") == "10"
    assert canonicalize_size("Men's Medium") == "M"
    assert canonicalize_size("Men's Large") == "L"
    assert canonicalize_size("Women's Small") == "S"
    assert canonicalize_size("Size: Extra Large") == "XL"
    assert canonicalize_size("Size Extra Small") == "XS"
    assert canonicalize_size("Women's") == "Women's"
    assert canonicalize_size("Men's") == "Men's"
    assert canonicalize_size("Levi's") == "Levi's"
    assert canonicalize_size(None) is None


def test_coerce_numeric():
    assert coerce_numeric(70) == 70.0
    assert coerce_numeric(70.5) == 70.5
    assert coerce_numeric("70") == 70.0
    assert coerce_numeric("$70") == 70.0
    assert coerce_numeric("$70.00") == 70.0
    assert coerce_numeric("70 dollars") == 70.0
    assert coerce_numeric("70 USD") == 70.0
    assert coerce_numeric("30L") == 30.0
    assert coerce_numeric("30 liters") == 30.0
    assert coerce_numeric("~30L") == 30.0
    assert coerce_numeric("approx 30 liters") == 30.0
    assert coerce_numeric("approx. 30 liters") == 30.0
    assert coerce_numeric("approx $70") == 70.0
    assert coerce_numeric("approx. $70") == 70.0
    assert coerce_numeric("around $50") == 50.0
    assert coerce_numeric("~ $70") == 70.0
    assert coerce_numeric("about 25L") == 25.0
    assert coerce_numeric(True) is None
    assert coerce_numeric(False) is None
    assert coerce_numeric("not a number") is None


def test_normalize_constraints_alias_and_coercion():
    obs = _make_obs("prod-1", "jackets", size="M", price=89.0, waterproof=True)
    listings = [obs]

    # Size alias: "medium" -> coerced to "M"
    c_size_med = [Constraint(attribute="size", operator=Operator.EQ, value="medium")]
    norm = Agent.normalize_constraints(c_size_med, listings)
    assert norm[0].value == "M"

    # Numeric-string equivalence: 9 (int) when listing is "9" (str)
    obs_shoe = _make_obs("shoe-1", "footwear", size="9", price=100.0)
    c_size_num = [Constraint(attribute="size", operator=Operator.EQ, value=9)]
    norm = Agent.normalize_constraints(c_size_num, [obs_shoe])
    assert norm[0].value == "9"

    # US sizing coercion: "US 9 men's" -> coerced to "9"
    c_size_us = [Constraint(attribute="size", operator=Operator.EQ, value="US 9 men's")]
    norm = Agent.normalize_constraints(c_size_us, [obs_shoe])
    assert norm[0].value == "9"

    # Reject genuinely different size values: "S" when listing is "M"
    c_size_s = [Constraint(attribute="size", operator=Operator.EQ, value="S")]
    norm = Agent.normalize_constraints(c_size_s, listings)
    assert norm[0].value == "S"  # NOT coerced to "M"

    # Reject genuinely different shoe size: 10 when listing is "9"
    c_size_10 = [Constraint(attribute="size", operator=Operator.EQ, value="10")]
    norm = Agent.normalize_constraints(c_size_10, [obs_shoe])
    assert norm[0].value == "10"  # NOT coerced to "9"

    # Price unit coercion: "$70.00" -> 70.0
    c_price = [Constraint(attribute="price", operator=Operator.LTE, value="$70.00")]
    norm = Agent.normalize_constraints(c_price, listings)
    assert norm[0].value == 70.0

    # Waterproof boolean string coercion: "true" -> True
    c_wp = [Constraint(attribute="waterproof", operator=Operator.EQ, value="true")]
    norm = Agent.normalize_constraints(c_wp, listings)
    assert norm[0].value is True

    # Approximate capacity coercion with tolerance
    obs_bag = _make_obs("bag-1", "bags", capacity_liters=30.0)
    c_cap = [Constraint(attribute="capacity_liters", operator=Operator.EQ, value="~30L")]
    norm = Agent.normalize_constraints(c_cap, [obs_bag])
    assert norm[0].value == 30.0
    assert norm[0].tolerance == 5.0


def test_matches_size_canonicalization():
    obs_jacket = _make_obs("jacket-m", "jackets", size="M")
    # "medium" matches "M"
    assert matches(obs_jacket.product, Constraint(attribute="size", operator="eq", value="medium"))
    assert matches(obs_jacket.product, Constraint(attribute="size", operator="eq", value="Medium"))
    assert matches(obs_jacket.product, Constraint(attribute="size", operator="eq", value="M"))
    # "small" does NOT match "M"
    assert not matches(obs_jacket.product, Constraint(attribute="size", operator="eq", value="small"))
    assert not matches(obs_jacket.product, Constraint(attribute="size", operator="eq", value="S"))

    obs_shoe = _make_obs("shoe-9", "footwear", size="9")
    # 9 (int), "9" (str), "US 9 men's" all match "9"
    assert matches(obs_shoe.product, Constraint(attribute="size", operator="eq", value=9))
    assert matches(obs_shoe.product, Constraint(attribute="size", operator="eq", value="9"))
    assert matches(obs_shoe.product, Constraint(attribute="size", operator="eq", value="US 9 men's"))
    assert matches(obs_shoe.product, Constraint(attribute="size", operator="eq", value="Men's US 9"))
    # 10 does NOT match "9"
    assert not matches(obs_shoe.product, Constraint(attribute="size", operator="eq", value=10))
    assert not matches(obs_shoe.product, Constraint(attribute="size", operator="eq", value="10"))

    # Ordering comparisons on formatted shoe sizes
    obs_shoe_half = _make_obs("shoe-9-5", "footwear", size="US 9.5 Men's")
    assert matches(obs_shoe_half.product, Constraint(attribute="size", operator=Operator.GTE, value=9))
    assert matches(obs_shoe_half.product, Constraint(attribute="size", operator=Operator.LTE, value=10))
    assert not matches(obs_shoe_half.product, Constraint(attribute="size", operator=Operator.GTE, value=10))


def test_verification_failure_observation_includes_observed_values():
    rejection = VerificationRejection(
        product_id="test-prod",
        reason="size eq 'M' fail (observed 'S'); price lte 50 fail (observed 79.0)",
        response_text="I picked test-prod.",
        price=79.0,
        stock=3,
        size="S",
        attributes={"color": "blue", "waterproof": True, "size": "S"},
    )
    obs_json = Agent._verification_observation(
        rejection,
        products={},
        rejected_ids=["test-prod"],
        turns_remaining=5,
    )
    data = json.loads(obs_json)
    assert data["type"] == "verification_failure"
    assert data["rejected_product_id"] == "test-prod"
    assert data["observed_price"] == 79.0
    assert data["observed_stock"] == 3
    assert data["observed_size"] == "S"
    assert data["observed_attributes"] == {"color": "blue", "waterproof": True, "size": "S"}
    assert data["turns_remaining"] == 5


def test_dead_repair_branch_fixed_in_finish():
    """In a repair turn, model-corrected constraints are used for the gate."""
    agent = Agent(api_key="test-key")
    obs = _make_obs("prod-runner-up", "jackets", size="M", price=85.0, waterproof=True, stock=4)

    mock_tools = MagicMock()
    mock_tools.get_listing.return_value = obs
    mock_tools.inspect_cart.return_value = MagicMock(items=[])
    mock_tools.add_to_cart.return_value = MagicMock(
        items=[MagicMock(product_id="prod-runner-up", quantity=1, in_stock=True, unit_price=85.0)]
    )

    # Initial captured interpretation was strict budget <= 70
    captured_constraints = [
        Constraint(attribute="category", operator=Operator.EQ, value="jackets", hard=True),
        Constraint(attribute="waterproof", operator=Operator.EQ, value=True, hard=True),
        Constraint(attribute="price", operator=Operator.LTE, value=70.0, hard=True),
    ]

    # Model in repair turn realizes budget is actually <= 100 and updates its constraints
    corrected_decision = {
        "status": "completed",
        "product_id": "prod-runner-up",
        "response": "Selected prod-runner-up with adjusted $100 budget.",
        "constraints": [
            {"attribute": "category", "operator": "eq", "value": "jackets", "hard": True},
            {"attribute": "waterproof", "operator": "eq", "value": True, "hard": True},
            {"attribute": "price", "operator": "lte", "value": 100.0, "hard": True},
        ],
        "ranking_rule": "lowest_price",
    }
    answer = {"content": [{"type": "text", "text": json.dumps(corrected_decision)}], "stop_reason": "end_turn"}
    inputs = AgentInput(
        request=ShoppingRequest(original_text="Need a waterproof jacket, max 100."),
        ranking_rule="lowest_price",
    )

    # In a repair turn (is_repair=True), the model's corrected constraints are used!
    outcome = agent.finish(
        decision=corrected_decision,
        provider_answer=answer,
        inputs=inputs,
        tools=mock_tools,
        products={"prod-runner-up": obs},
        active_constraints=captured_constraints,
        active_ranking_rule="lowest_price",
        is_repair=True,
    )
    assert outcome.termination_reason == "completed"
    assert outcome.selected_product_ids == ["prod-runner-up"]
    # Verify the gate used the corrected constraints (price <= 100), not the old 70
    assert any(c["attribute"] == "price" and c["value"] == 100.0 for c in outcome.diagnostics["interpreted_constraints"])


def test_prompts_free_of_benchmark_specific_phrases():
    """Ensure agent prompts do not contain benchmark-aliased phrases."""
    # Prompts must not alias specific benchmark tasks
    assert "~30 liter" not in PROMPT
    assert "~30 liter" not in INTERPRETATION_PROMPT
    assert "daypack sized" not in PROMPT
    assert "daypack sized" not in INTERPRETATION_PROMPT
    assert "US 9 men's" not in PROMPT
    assert "US 9 men's" not in INTERPRETATION_PROMPT
    assert "25 and lte 35" not in INTERPRETATION_PROMPT
    assert "gte 20 and lte 25" not in INTERPRETATION_PROMPT


def test_task_definition_constraints_property():
    _, tasks = load_examples()
    for task in tasks.values():
        assert hasattr(task, "constraints")
        assert task.constraints == task.request.constraints


def test_repair_differ_handles_heterogeneous_types():
    """In repair turn, sorting constraints with mixed types does not raise TypeError."""
    agent = Agent(api_key="test-key")
    obs = _make_obs("prod-1", "bags", size="9", price=85.0, waterproof=True, stock=4, capacity_liters=30.0)

    mock_tools = MagicMock()
    mock_tools.get_listing.return_value = obs
    mock_tools.inspect_cart.return_value = MagicMock(items=[])
    mock_tools.add_to_cart.return_value = MagicMock(
        items=[MagicMock(product_id="prod-1", quantity=1, in_stock=True, unit_price=85.0)]
    )

    # Active constraints have float tolerance on capacity and string size
    captured_constraints = [
        Constraint(attribute="capacity_liters", operator=Operator.EQ, value=30.0, tolerance=5.0, hard=True),
        Constraint(attribute="size", operator=Operator.EQ, value="9", hard=True),
        Constraint(attribute="price", operator=Operator.LTE, value=100.0, hard=True),
    ]

    # Model constraints have None tolerance and int size
    corrected_decision = {
        "status": "completed",
        "product_id": "prod-1",
        "response": "Selected prod-1.",
        "constraints": [
            {"attribute": "capacity_liters", "operator": "eq", "value": 30.0, "hard": True},
            {"attribute": "size", "operator": "eq", "value": 9, "hard": True},
            {"attribute": "price", "operator": "lte", "value": 100.0, "hard": True},
        ],
        "ranking_rule": "lowest_price",
    }
    answer = {"content": [{"type": "text", "text": json.dumps(corrected_decision)}], "stop_reason": "end_turn"}
    inputs = AgentInput(
        request=ShoppingRequest(original_text="Need a pack and shoes."),
        ranking_rule="lowest_price",
    )

    # Should not raise TypeError: '<' not supported between instances
    outcome = agent.finish(
        decision=corrected_decision,
        provider_answer=answer,
        inputs=inputs,
        tools=mock_tools,
        products={"prod-1": obs},
        active_constraints=captured_constraints,
        active_ranking_rule="lowest_price",
        is_repair=True,
    )
    assert outcome.termination_reason == "completed"
