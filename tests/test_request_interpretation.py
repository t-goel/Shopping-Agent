import json

import pytest

from shopping_agent.agent.agent import Agent


def test_llm_interpretation_is_validated_and_preserves_original_query(monkeypatch):
    response = {
        "content": [{
            "type": "text",
            "text": json.dumps({
                "request": {
                    "original_text": "wrong text",
                    "constraints": [
                        {"attribute": "category", "operator": "eq", "value": "jackets"},
                        {"attribute": "price", "operator": "lte", "value": 100},
                    ],
                    "preferences": ["lightweight"],
                    "clarification_needed": None,
                },
                "ranking_rule": "lowest_price",
            }),
        }],
    }

    class Response:
        status_code = 200

        def json(self):
            return response

    monkeypatch.setattr("shopping_agent.agent.agent.requests.post", lambda *args, **kwargs: Response())
    query = "Find a lightweight rain jacket below $100"
    interpretation = Agent(api_key="test").interpret_query(query)

    assert interpretation.request.original_text == query
    assert interpretation.request.constraints[1].value == 100
    assert interpretation.ranking_rule == "lowest_price"


def test_llm_interpretation_rejects_invalid_constraint(monkeypatch):
    response = {
        "content": [{"type": "text", "text": '{"request": {}, "ranking_rule": "none"}'}],
    }

    class Response:
        status_code = 200

        def json(self):
            return response

    monkeypatch.setattr("shopping_agent.agent.agent.requests.post", lambda *args, **kwargs: Response())

    with pytest.raises(RuntimeError, match="invalid request interpretation"):
        Agent(api_key="test").interpret_query("Find something")
