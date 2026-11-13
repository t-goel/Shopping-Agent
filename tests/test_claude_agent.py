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
