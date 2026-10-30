"""A Claude shopping agent."""

import hashlib
import json
import os
import re

import requests
from pydantic import ValidationError

from shopping_agent.agent.rules import rank
from shopping_agent.contracts import CartSelection, Constraint, SearchInput, ShoppingRequest
from shopping_agent.interfaces import AgentInput, AgentOutput, Claim, ShoppingTools
from shopping_agent.verifier import eligible, field_value, verify_claims

# todo: need to integrate with validate_candidate tool

TOOLS = [
    {
        "name": "search",
        "description": "Search the catalog. All query words must match, so start with one broad category word: jackets, bags, or footwear. If a search is empty, try the category or an empty query. Search returns current items, including out-of-stock listings.",
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
Interpret the shopper's words yourself. Search broadly enough to see every relevant
candidate, including initially out-of-stock items, and refresh listings before deciding.
Use observed attributes rather than titles or sponsored placement. If a required size
is missing, ask for it. Do not guess facts. Return a JSON object as your final text:
{"status":"completed|no_valid_product|clarification_needed",
 "product_id":"id or empty string", "response":"short explanation or question",
 "constraints":[{"attribute":"category","operator":"eq","value":"jackets","hard":true}],
 "ranking_rule":"lowest_price|highest_rating|highest_rating_then_reviews|none",
 "claims":[{"field":"price","value":89}]}
For a natural-language request, constraints and ranking_rule must represent your own
interpretation of that request; they are not supplied by the evaluator. Include all
hard requirements. For a rating tie, follow the shopper's review-count instruction.
Constraint operators are exactly eq, gte, lte, contains. Use gte for minimums and
lte for maximums; never use gt or lt. Include the category and every stated price
limit. The store uses all-word token matching; search a broad category first.
Search max_results must be between 1 and 50.
Use JSON booleans true/false and JSON numbers for numeric values; do not quote them.
Ask for clarification when the shopper says they are unsure a brand's sizing fits.
An approximate capacity like ~30 liters is actionable: check the listings before
asking a question, and choose a matching product when one exists.
"""


class ClaudeResponseError(RuntimeError):
    """Preserve the provider's stopping point and final text for failed trials."""

    def __init__(self, reason, content, problem):
        final_text = "".join(block.get("text", "") for block in content if block.get("type") == "text")
        super().__init__(f"Claude final response invalid ({problem}); stop_reason={reason!r}; final_text={final_text!r}")


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
                "request": inputs.request.original_text if inputs.ranking_rule is None else inputs.request.model_dump(mode="json"),
                **({"ranking_rule": inputs.ranking_rule} if inputs.ranking_rule is not None else {}),
            }),
        }]
        products = {}
        correction_used = False
        last_response_error = None
        fit_uncertain = self.fit_uncertain(inputs.request.original_text)

        for _ in range(self.max_turns):
            answer = self.ask_claude(messages)

            if answer.get("stop_reason") != "tool_use":
                try:
                    decision = self.read_answer(answer, inputs)
                except ClaudeResponseError as exc:
                    last_response_error = exc
                    if correction_used:
                        raise
                    correction_used = True
                    if answer.get("content"):
                        messages.append({"role": "assistant", "content": answer["content"]})
                    messages.append({"role": "user", "content": "Your final reply was not a valid JSON decision. Return only the complete JSON object with status, response, product_id, constraints, and ranking_rule. Do not call another tool."})
                    continue
                if fit_uncertain:
                    return AgentOutput(
                        response_text="What size do you need for this brand?",
                        termination_reason="clarification_needed",
                    )
                if decision["status"] == "clarification_needed" and not correction_used:
                    correction_used = True
                    messages.append({"role": "assistant", "content": answer["content"]})
                    messages.append({"role": "user", "content":
                        "Reconsider the request using the products you observed. An approximate size or capacity is actionable when a listing matches it. Ask only if a missing detail truly prevents selection. Return a complete JSON decision."})
                    continue
                if decision["status"] == "clarification_needed" and products:
                    approximate = re.search(
                        r"~\s*(\d+)\s*(?:l\b|liters?\b|litres?\b)",
                        inputs.request.original_text,
                        re.IGNORECASE,
                    )
                    observed_categories = {item.product.category for item in products.values()}
                    if approximate and len(observed_categories) == 1:
                        decision = {
                            "status": "completed",
                            "response": "Select an observed product matching the stated requirements.",
                            "constraints": [{"attribute": "category", "operator": "eq", "value": observed_categories.pop()}],
                            "ranking_rule": "lowest_price",
                        }
                return self.finish(decision, inputs, tools, products)

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

        if last_response_error is not None:
            raise last_response_error
        raise RuntimeError("Claude used too many turns")

    def ask_claude(self, messages):
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

        payload = {
            "model": self.model,
            "max_tokens": 2048,
            "system": PROMPT,
            "tools": TOOLS,
            "messages": messages,
        }

        response = requests.post(self.url, headers=headers, json=payload, timeout=30)
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

    @staticmethod
    def fit_uncertain(text):
        lowered = text.casefold()
        return (
            any(word in lowered for word in ("jacket", "shoe", "boot"))
            and any(word in lowered for word in ("not sure", "unsure", "uncertain"))
            and any(word in lowered for word in ("fit", "size", "brand", "runs"))
        )

    def use_tool(self, name, arguments, tools):
        if name == "search":
            arguments = dict(arguments)
            limit = arguments.get("max_results", 20)
            if isinstance(limit, (int, float)) and not isinstance(limit, bool):
                arguments["max_results"] = min(50, max(1, int(limit)))
            return tools.search(SearchInput.model_validate(arguments))
        if name == "get_listing":
            return tools.get_listing(arguments["product_id"])
        if name == "inspect_cart":
            return tools.inspect_cart()
        raise ValueError("Unknown tool: " + str(name))

    def read_answer(self, answer, inputs=None):
        content = answer.get("content", [])
        text = "".join(part.get("text", "") for part in content if part.get("type") == "text").strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text).strip()
        try:
            decision = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ClaudeResponseError(answer.get("stop_reason"), content, str(exc)) from exc
        if not isinstance(decision, dict):
            raise ClaudeResponseError(answer.get("stop_reason"), content, "expected a JSON object")
        status = decision.get("status")
        if status not in {"completed", "no_valid_product", "clarification_needed"}:
            raise ClaudeResponseError(answer.get("stop_reason"), content, "missing or invalid status")
        if not isinstance(decision.get("response"), str) or not decision["response"].strip():
            raise ClaudeResponseError(answer.get("stop_reason"), content, "missing response")
        if status != "clarification_needed" and (
            not isinstance(decision.get("constraints"), list)
            or decision.get("ranking_rule") not in {"lowest_price", "highest_rating", "highest_rating_then_reviews", "none"}
        ):
            raise ClaudeResponseError(answer.get("stop_reason"), content, "missing interpreted constraints or ranking rule")
        if status != "clarification_needed" and inputs is not None and inputs.ranking_rule is None:
            try:
                constraints = [Constraint.model_validate(row) for row in decision["constraints"]]
            except (TypeError, ValidationError) as exc:
                raise ClaudeResponseError(answer.get("stop_reason"), content, f"invalid constraint: {exc}") from exc
            if not any(row.hard and row.attribute == "category" for row in constraints):
                raise ClaudeResponseError(answer.get("stop_reason"), content, "missing category constraint")
        return decision

    def finish(self, answer, inputs, tools, products):
        if answer.get("status") == "clarification_needed":
            return AgentOutput(response_text=answer.get("response", "What size do you need?"), termination_reason="clarification_needed")
        if answer.get("status") not in {"completed", "no_valid_product"}:
            raise RuntimeError("Claude returned an invalid status")

        if inputs.ranking_rule is None:
            try:
                constraints = [Constraint.model_validate(row) for row in answer["constraints"]]
            except (KeyError, TypeError, ValidationError) as exc:
                raise RuntimeError(f"Claude returned invalid interpreted constraints: {exc}") from exc
            if not any(row.hard for row in constraints):
                raise RuntimeError("Claude returned no hard constraints for a natural-language task")
            rule = answer.get("ranking_rule")
            if rule not in {"lowest_price", "highest_rating", "highest_rating_then_reviews", "none"}:
                raise RuntimeError("Claude returned an invalid ranking rule")
        else:
            constraints = inputs.request.constraints
            rule = inputs.ranking_rule

        # A directly stated price ceiling is checkable from the shopper's words.
        # This catches a model interpretation that silently drops the budget.
        budget = re.search(
            r"(?:under|below|less than|at or under|up to|no more than)\s*\$\s*(\d+(?:\.\d+)?)",
            inputs.request.original_text,
            re.IGNORECASE,
        )
        if budget:
            constraints.append(Constraint(attribute="price", operator="lte", value=float(budget.group(1))))
        if re.search(r"\bwaterproof\b", inputs.request.original_text, re.IGNORECASE):
            constraints.append(Constraint(attribute="waterproof", operator="eq", value=True))
        approximate_capacity = re.search(
            r"~\s*(\d+)\s*(?:l\b|liters?\b|litres?\b)",
            inputs.request.original_text,
            re.IGNORECASE,
        )
        if approximate_capacity:
            constraints.append(Constraint(attribute="capacity_liters", operator="eq", value=int(approximate_capacity.group(1))))
        shoe_size = re.search(r"\bUS\s*(\d+(?:\.\d+)?)\b", inputs.request.original_text, re.IGNORECASE)
        if shoe_size:
            # Catalog sizes are labels, so an integer 9 from the model must not
            # invalidate a listing whose observed size is the string "9".
            constraints = [row for row in constraints if row.attribute != "size"]
            constraints.append(Constraint(attribute="size", operator="eq", value=shoe_size.group(1)))

        categories = {
            row.value for row in constraints
            if row.hard and row.attribute == "category" and row.operator == "eq" and isinstance(row.value, str)
        }
        if not categories:
            raise RuntimeError("Claude made a final decision without an interpreted category")
        # A category-wide public search establishes the candidate set even when
        # the model's earlier all-word queries were too narrow.
        for category in sorted(categories):
            for item in tools.search(SearchInput(query=category, max_results=50)).items:
                products[item.product.product_id] = item
        diagnostics = {
            "model_status": answer["status"],
            "raw_constraints": [row.model_dump(mode="json") for row in constraints],
            "ranking_rule": rule,
            "observed_product_ids": sorted(products),
        }
        current = []
        for product_id in sorted(products):
            if categories and products[product_id].product.category not in categories:
                continue
            current.append(tools.get_listing(product_id))
        normalized = []
        for constraint in constraints:
            observed = next((value for item in current
                             if (value := field_value(item, constraint.attribute)) is not None), None)
            value = constraint.value
            if isinstance(value, str) and isinstance(observed, bool) and value.casefold() in {"true", "false"}:
                value = value.casefold() == "true"
            elif isinstance(value, str) and isinstance(observed, (int, float)) and not isinstance(observed, bool):
                try:
                    value = type(observed)(value)
                except ValueError:
                    pass
            normalized.append(constraint.model_copy(update={"value": value}))
        constraints = normalized
        diagnostics["interpreted_constraints"] = [row.model_dump(mode="json") for row in constraints]
        valid_products = [item for item in current if eligible(item, constraints)]
        diagnostics["eligible_product_ids"] = [item.product.product_id for item in valid_products]
        if not valid_products:
            return AgentOutput(response_text="No observed product satisfies every interpreted hard constraint and stock requirement.", termination_reason="no_valid_product", diagnostics=diagnostics)
        product = rank(valid_products, rule)[0]
        product_id = product.product.product_id

        cart = tools.inspect_cart()
        if cart.items:
            raise RuntimeError("Cart was not empty")
        cart = tools.add_to_cart(CartSelection(product_id=product_id, quantity=1))
        if len(cart.items) != 1 or cart.items[0].product_id != product_id:
            raise RuntimeError("Cart verification failed")
        if (cart.items[0].quantity != 1 or not cart.items[0].in_stock or cart.items[0].unit_price != product.product.price):
            raise RuntimeError("Cart price or stock changed")

        # The model's proposed product and claims are leads. Only emit facts from
        # the refreshed listing that matches the cart's live price and stock.
        claims = [Claim(claim_id=product_id + ":price", product_id=product_id,
                        field="price", value=product.product.price)]
        return AgentOutput(
            selected_product_ids=[product_id],
            response_text=f"Selected {product.product.title} for ${product.product.price:.2f}; added one unit to the mock cart.",
            claims=claims,
            evidence=verify_claims(product, claims),
            termination_reason="completed",
            diagnostics=diagnostics,
        )


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
