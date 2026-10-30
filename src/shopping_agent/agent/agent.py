"""A Claude shopping agent."""

import hashlib
import json
import os
import re

import requests

from shopping_agent.agent.rules import rank
from shopping_agent.contracts import CartSelection, Constraint, SearchInput, ShoppingRequest
from shopping_agent.interfaces import AgentInput, AgentOutput, Claim, ShoppingTools
from shopping_agent.verifier import eligible, verify_claims

# todo: need to integrate with validate_candidate tool

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


class Agent:
    def __init__(self, api_key=None, model=None, max_turns=10):
        self.prompt_version = hashlib.sha256(
            (PROMPT + json.dumps(TOOLS, sort_keys=True)).encode()).hexdigest()
        self.input_tokens = None
        self.output_tokens = None
        self._missing_usage = set()
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        self.model = model or os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-5")
        self.max_turns = max_turns
        self.url = "https://api.anthropic.com/v1/messages"

    def run(self, inputs: AgentInput, tools: ShoppingTools) -> AgentOutput:
        self.input_tokens = None
        self.output_tokens = None
        self._missing_usage = set()
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
                    result = self.use_tool(
                        block["name"],
                        block["input"],
                        tools,
                    )

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
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

        json = {
            "model": self.model,
            "max_tokens": 2048,
            "system": PROMPT,
            "tools": TOOLS,
            "messages": messages,
        }

        response = requests.post(self.url, headers=headers, json=json, timeout=30)
        if response.status_code != 200:
            raise RuntimeError(f"Claude API error:{response.status_code} {response.text}")
        
        answer = response.json()
        usage = answer.get("usage", {})
        for field in ("input_tokens", "output_tokens"):
            value = usage.get(field)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                self._missing_usage.add(field)
                setattr(self, field, None)
            elif field not in self._missing_usage:
                setattr(self, field, (getattr(self, field) or 0) + value)
        return answer

    def use_tool(self, name, arguments, tools):
        if name == "search":
            return tools.search(SearchInput.model_validate(arguments))
        if name == "get_listing":
            return tools.get_listing(arguments["product_id"])
        if name == "inspect_cart":
            return tools.inspect_cart()
        raise ValueError("Unknown tool: " + str(name))

    def read_answer(self, content):
        text = "".join(part.get("text", "") for part in content if part.get("type") == "text").strip()
        if text.startswith("```"):
            text = text.replace("```json", "").replace("```", "").strip()
        answer = json.loads(text)
        if not isinstance(answer, dict): raise RuntimeError("Claude answer was not an object")
        return answer

    def finish(self, answer, inputs, tools, products):
        if answer.get("status") == "no_valid_product":
            return AgentOutput(response_text=answer.get("response", "No valid product was found."), termination_reason="no_valid_product")
        if answer.get("status") != "completed":
            raise RuntimeError("Claude returned an invalid status")

        product_id = answer.get("product_id")
        if not product_id:
            raise RuntimeError("Claude did not choose a product")
        product = tools.get_listing(product_id)

        if not eligible(product, inputs.request.constraints):
            return AgentOutput(response_text="The selected product failed verification.", termination_reason="no_valid_product")

        products[product_id] = product

        valid_products = [item for item in products.values() if eligible(item, inputs.request.constraints)]

        if valid_products:
            product = rank(valid_products, inputs.ranking_rule)[0]
            product_id = product.product.product_id

        cart = tools.inspect_cart()
        if cart.items:
            raise RuntimeError("Cart was not empty")
        cart = tools.add_to_cart(CartSelection(product_id=product_id, quantity=1))
        if len(cart.items) != 1 or cart.items[0].product_id != product_id:
            raise RuntimeError("Cart verification failed")
        if (cart.items[0].quantity != 1 or not cart.items[0].in_stock or cart.items[0].unit_price != product.product.price):
            raise RuntimeError("Cart price or stock changed")

        claims = []
        for item in answer.get("claims", []):
            if isinstance(item, dict) and "field" in item and "value" in item:
                claims.append(Claim(claim_id=product_id + ":" + item["field"], product_id=product_id, field=item["field"], value=item["value"]))
        if not claims:
            claims.append(Claim(claim_id=product_id + ":price", product_id=product_id, field="price", value=product.product.price))

        return AgentOutput(selected_product_ids=[product_id], response_text=answer.get("response", "Selected " + product.product.title + "."), claims=claims, evidence=verify_claims(product, claims), termination_reason="completed")


def runAgent(query, tools):
    text = query.casefold()
    constraints = []

    #this is intentionally small. The normal evaluator already supplies parsed requests.
    if "jacket" in text:
        constraints.append(Constraint(attribute="category", operator="eq", value="jackets"))
    if "waterproof" in text:
        constraints.append(Constraint(attribute="waterproof", operator="eq", value=True))

    size = re.search(r"size\s+([a-z])", text)
    if size:
        constraints.append(Constraint(attribute="size",operator="eq", value=size.group(1).upper()))

    price = re.search(r"(?:under|less than)\s*\$?(\d+(?:\.\d+)?)", text)
    if price:
        constraints.append(Constraint(attribute="price", operator="lte", value=float(price.group(1))))

    return Agent().run(AgentInput(request=ShoppingRequest(original_text=query, constraints=constraints), ranking_rule="lowest_price" if "cheapest" in text else "none"), tools)
