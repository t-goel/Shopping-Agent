"""A Claude shopping agent."""

import json
import os

import requests
from pydantic import ValidationError

from shopping_agent.agent.rules import rank
from shopping_agent.contracts import (
    CartSelection,
    ClaudeAnswer,
    RequestInterpretation,
    SearchInput,
)
from shopping_agent.interfaces import AgentInput, AgentOutput, Claim, ShoppingTools
from shopping_agent.tools.api import ToolError
from shopping_agent.verifier import eligible, verify_claims

TOOLS = [
    {
        "name": "search",
        "description": "Search the product catalog.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "max_results": {"type": "integer"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_listing",
        "description": "Get current details for one product.",
        "input_schema": {
            "type": "object",
            "properties": {"product_id": {"type": "string"}},
            "required": ["product_id"],
        },
    },
    {
        "name": "inspect_cart",
        "description": "Read the mock cart.",
        "input_schema": {"type": "object", "properties": {}},
    },
]


PROMPT = """
You are a shopping agent.
Use the tools to find and check products. Do not guess facts. Follow all hard
constraints and the ranking rule. Return JSON only:
{"status":"completed" or "no_valid_product",
 "product_id":"id or empty string",
 "claims":[{"field":"price","value":89}],
 "response":"short explanation"}
"""

INTERPRETATION_PROMPT = """
You convert a user's shopping request into the project's typed shopping schema.
Return JSON only, with this exact shape:
{
  "request": {
    "original_text": "the original request",
    "constraints": [
      {
        "attribute": "supported product attribute",
        "operator": "eq|gte|lte|contains",
        "value": "string, number, or boolean",
        "hard": true
      }
    ],
    "preferences": ["soft preference"],
    "clarification_needed": "question or null"
  },
  "ranking_rule": "lowest_price|highest_rating|none"
}

Extract only constraints that are stated or clearly implied. Use hard=true
only for requirements; put preferences in preferences. Never invent product
facts. If the request does not identify a product category, set
clarification_needed to a concise question. Use the original request exactly.
"""


class Agent:
    def __init__(self, api_key=None, model=None, max_turns=10):
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        self.model = model or os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-5")
        self.max_turns = max_turns
        self.url = "https://api.anthropic.com/v1/messages"

    def interpret_query(self, query: str) -> RequestInterpretation:
        """Use Claude to turn free-form language into a validated request."""
        if not query or not query.strip():
            raise ValueError("shopping query must not be empty")
        if not self.api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set")

        response = self.ask_json(
            system=INTERPRETATION_PROMPT,
            content=query,
        )
        try:
            interpretation = RequestInterpretation.model_validate_json(response)
        except (TypeError, ValueError, ValidationError) as exc:
            raise RuntimeError("Claude returned invalid request interpretation") from exc

        if interpretation.request.original_text != query:
            interpretation.request.original_text = query
        return interpretation

    def run(self, inputs: AgentInput, tools: ShoppingTools) -> AgentOutput:
        if inputs.request.clarification_needed:
            return AgentOutput(response_text=inputs.request.clarification_needed, termination_reason="clarification_needed")
        if not self.api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set")

        messages = [{
            "role": "user",
            "content": json.dumps({
                "request": inputs.request.model_dump(mode="json"),
                "ranking_rule": inputs.ranking_rule,
            }),
        }]
        products = {}

        for _ in range(self.max_turns):
            answer = self.ask_claude(messages)

            if answer.get("stop_reason") != "tool_use":
                return self.finish(self.read_answer(answer["content"]), inputs, tools, products)

            tool_results = []
            for block in answer["content"]:
                if block.get("type") == "tool_use":
                    try:
                        result = self.use_tool(block["name"], block["input"], tools)
                    except (KeyError, ToolError, ValidationError, ValueError) as exc:
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block["id"],
                            "content": f"{type(exc).__name__}: {exc}",
                            "is_error": True,
                        })
                        continue

                    if block["name"] == "search":
                        for item in result.items:
                            products[item.product.product_id] = item
                    elif block["name"] == "get_listing":
                        products[result.product.product_id] = result

                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block["id"],
                        "content": result.model_dump_json(),
                    })

            messages.append({"role": "assistant", "content": answer["content"]})
            messages.append({"role": "user", "content": tool_results})

        raise RuntimeError("Claude used too many turns")

    def ask_claude(self, messages):
        return self._post_messages(system=PROMPT, messages=messages, tools=TOOLS)

    def ask_json(self, system: str, content: str) -> str:
        answer = self._post_messages(
            system=system,
            messages=[{"role": "user", "content": content}],
            tools=[],
        )
        return self._text_content(answer.get("content", []))

    def _post_messages(self, system: str, messages: list[dict], tools: list[dict]):
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

        json = {
            "model": self.model,
            "max_tokens": 2048,
            "system": system,
            "tools": tools,
            "messages": messages,
        }

        response = requests.post(self.url, headers=headers, json=json, timeout=30)
        if response.status_code != 200:
            raise RuntimeError(f"Claude API error:{response.status_code} {response.text}")
        
        return response.json()

    def use_tool(self, name, arguments, tools):
        if name == "search":
            return tools.search(SearchInput.model_validate(arguments))
        if name == "get_listing":
            return tools.get_listing(arguments["product_id"])
        if name == "inspect_cart":
            return tools.inspect_cart()
        raise ValueError("Unknown tool: " + str(name))

    def read_answer(self, content) -> ClaudeAnswer:
        text = self._text_content(content)
        if text.startswith("```"):
            text = text.replace("```json", "").replace("```", "").strip()
        try:
            return ClaudeAnswer.model_validate_json(text)
        except (TypeError, ValueError, ValidationError) as exc:
            raise RuntimeError("Claude returned invalid shopping JSON") from exc

    @staticmethod
    def _text_content(content: list[dict]) -> str:
        text = "".join(
            part.get("text", "")
            for part in content
            if part.get("type") == "text"
        ).strip()
        if text.startswith("```"):
            text = text.replace("```json", "").replace("```", "").strip()
        return text

    def finish(self, answer: ClaudeAnswer, inputs, tools, products):
        if answer.status == "no_valid_product":
            return AgentOutput(
                response_text=answer.response or "No valid product was found.",
                termination_reason="no_valid_product",
            )

        selected = tools.get_listing(answer.product_id)
        products[answer.product_id] = selected

        # Refresh every known candidate before ranking so the model cannot
        # commit a stale search result when price or stock has changed.
        current = {}
        for candidate_id in products:
            try:
                latest = tools.get_listing(candidate_id)
            except ToolError as exc:
                if exc.status_code == 404:
                    continue
                raise
            if eligible(latest, inputs.request.constraints):
                current[candidate_id] = latest

        if not current:
            return AgentOutput(
                response_text="The selected product failed verification.",
                termination_reason="no_valid_product",
            )

        product = rank(list(current.values()), inputs.ranking_rule)[0]
        product_id = product.product.product_id

        # Verify the winner once more immediately before the write.
        latest = tools.get_listing(product_id)
        if not eligible(latest, inputs.request.constraints):
            return AgentOutput(
                response_text="The selected product changed before checkout.",
                termination_reason="no_valid_product",
            )
        product = latest

        cart = tools.inspect_cart()
        if cart.items:
            raise RuntimeError("Cart was not empty")
        cart = tools.add_to_cart(CartSelection(product_id=product_id, quantity=1))
        if len(cart.items) != 1 or cart.items[0].product_id != product_id:
            raise RuntimeError("Cart verification failed")
        if (cart.items[0].quantity != 1 or not cart.items[0].in_stock or cart.items[0].unit_price != product.product.price):
            raise RuntimeError("Cart price or stock changed")

        claims = [
            Claim(
                claim_id=product_id + ":" + item.field,
                product_id=product_id,
                field=item.field,
                value=item.value,
            )
            for item in answer.claims
        ]
        if not claims:
            claims.append(Claim(claim_id=product_id + ":price", product_id=product_id, field="price", value=product.product.price))

        return AgentOutput(
            selected_product_ids=[product_id],
            response_text=answer.response or "Selected " + product.product.title + ".",
            claims=claims,
            evidence=verify_claims(product, claims),
            termination_reason="completed",
        )


def runAgent(query, tools):
    agent = Agent()
    interpretation = agent.interpret_query(query)
    return agent.run(
        AgentInput(
            request=interpretation.request,
            ranking_rule=interpretation.ranking_rule,
        ),
        tools,
    )
