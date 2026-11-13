import pytest

from shopping_agent.agent.request_parser import parse_request


def test_parser_handles_synonyms_and_natural_price_language():
    request, ranking = parse_request(
        "Please find the least expensive rain shell, medium size, below $100"
    )

    assert ranking == "lowest_price"
    assert {(c.attribute, c.operator, c.value) for c in request.constraints} == {
        ("category", "eq", "jackets"),
        ("size", "eq", "M"),
        ("price", "lte", 100.0),
    }
    assert request.clarification_needed is None


def test_parser_preserves_negation_and_high_rating_preference():
    request, ranking = parse_request("Find a non-waterproof backpack over $20, best rated")

    assert ranking == "highest_rating"
    assert {(c.attribute, c.operator, c.value) for c in request.constraints} == {
        ("category", "eq", "bags"),
        ("waterproof", "eq", False),
        ("price", "gte", 20.0),
    }


def test_parser_requests_clarification_when_category_is_missing():
    request, ranking = parse_request("Find something under $50")

    assert ranking == "none"
    assert [constraint.model_dump(mode="json") for constraint in request.constraints] == [{
        "attribute": "price", "operator": "lte", "value": 50.0, "hard": True,
    }]
    assert request.clarification_needed == "What type of product should I look for?"


@pytest.mark.parametrize("query", ["", "   "])
def test_parser_rejects_empty_queries(query):
    with pytest.raises(ValueError, match="must not be empty"):
        parse_request(query)
