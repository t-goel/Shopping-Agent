"""A Claude shopping agent."""

import hashlib
import json
import os
import re

import requests
from pydantic import ValidationError

from shopping_agent.contracts import (
    CartSelection,
    ClaudeAnswer,
    Constraint,
    RequestInterpretation,
    SearchInput,
    ShoppingRequest,
)
from shopping_agent.interfaces import AgentInput, AgentOutput, Claim, ShoppingTools
from shopping_agent.tools.api import ToolError
from shopping_agent.verifier import eligible, field_value, verify_claims

TOOLS = [
    {
        "name": "list_stores",
        "description": (
            "List storefronts. Call this first. On multi-store catalogs every search "
            "needs a store_id from this list. If the tool returns mode=flat, search "
            "without store_id."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "search",
        "description": (
            "Search one storefront catalog. All query words must match, so start with "
            "one broad category word: jackets, bags, or footwear. If a search is empty, "
            "try the category or an empty query. Search returns current items, including "
            "out-of-stock listings. Pass store_id whenever list_stores returned stores."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "max_results": {"type": "integer"},
                "store_id": {"type": "string"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_listing",
        "description": (
            "Get current details for one product. Prefer listing_id when search returned "
            "one; otherwise pass product_id with store_id on multi-store catalogs."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "product_id": {"type": "string"},
                "store_id": {"type": "string"},
                "listing_id": {"type": "string"},
            },
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
Interpret the shopper's words yourself. Call list_stores first. When stores are present,
search each relevant store_id separately; never call search without store_id in that mode.
Search broadly enough to see every relevant candidate, including initially out-of-stock
items, and refresh listings before deciding. Prefer listing_id when choosing among
overlapping products sold in multiple stores.
Use observed attributes rather than titles or sponsored placement. If a required size
is missing, ask for it. Do not guess facts. Return a JSON object as your final text:
{"status":"completed|no_valid_product|clarification_needed",
 "product_id":"id or empty string",
 "listing_id":"store_id:product_id when known, else empty string",
 "store_id":"store id when known, else empty string",
 "response":"short explanation or question",
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


class ClaudeResponseError(RuntimeError):
    """Preserve the provider's stopping point and final text for failed trials."""

    def __init__(self, reason, content, problem):
        final_text = "".join(block.get("text", "") for block in content if block.get("type") == "text")
        super().__init__(
            f"Claude final response invalid ({problem}); stop_reason={reason!r}; final_text={final_text!r}"
        )


class Agent:
    def __init__(self, api_key=None, model=None, effort=None, max_turns=10):
        self.prompt_id = hashlib.sha256(
            (PROMPT + json.dumps(TOOLS, sort_keys=True)).encode()).hexdigest()
        self.input_tokens = None
        self.output_tokens = None
        self._missing_usage = set()
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        self.model = model or os.environ.get("ANTHROPIC_MODEL", "claude-haiku-5-5")
        self.effort = effort or os.environ.get("ANTHROPIC_EFFORT", "high")
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
        self.input_tokens = None
        self.output_tokens = None
        self._missing_usage = set()
        if inputs.request.clarification_needed:
            return AgentOutput(
                response_text=inputs.request.clarification_needed,
                termination_reason="clarification_needed",
            )
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
                    messages.append({
                        "role": "user",
                        "content": (
                            "Your final reply was not a valid JSON decision. Return only the complete "
                            "JSON object with status, response, product_id, constraints, and ranking_rule. "
                            "Do not call another tool."
                        ),
                    })
                    continue
                return self.finish(decision, answer, inputs, tools, products)

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
                            if item.listing_id:
                                products[item.listing_id] = item
                    elif block["name"] == "get_listing":
                        products[result.product.product_id] = result
                        if result.listing_id:
                            products[result.listing_id] = result
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block["id"],
                        "content": self._tool_content(result),
                    })

            messages.append({"role": "assistant", "content": answer["content"]})
            messages.append({"role": "user", "content": tool_results})

        if last_response_error is not None:
            raise last_response_error
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
        payload = {
            "model": self.model,
            # Thinking counts toward max_tokens on Haiku 5.5; leave room at high effort.
            "max_tokens": 8192,
            "system": system,
            "tools": tools,
            "messages": messages,
            "output_config": {"effort": self.effort},
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
    def _tool_content(result) -> str:
        if hasattr(result, "model_dump_json"):
            return result.model_dump_json()
        if isinstance(result, list):
            return json.dumps([
                row.model_dump(mode="json") if hasattr(row, "model_dump") else row
                for row in result
            ])
        return json.dumps(result)

    def use_tool(self, name, arguments, tools):
        arguments = dict(arguments or {})
        if name == "list_stores":
            try:
                stores = tools.list_stores()
            except ToolError as exc:
                if exc.status_code != 404:
                    raise
                return {"mode": "flat", "stores": []}
            return {
                "mode": "multi-store",
                "stores": [store.model_dump(mode="json") for store in stores],
            }
        if name == "search":
            limit = arguments.get("max_results", 20)
            if isinstance(limit, (int, float)) and not isinstance(limit, bool):
                arguments["max_results"] = min(50, max(1, int(limit)))
            store_id = arguments.get("store_id")
            if isinstance(store_id, str) and not store_id.strip():
                arguments.pop("store_id", None)
            return tools.search(SearchInput.model_validate(arguments))
        if name == "get_listing":
            listing_id = arguments.get("listing_id") or None
            product_id = arguments.get("product_id") or None
            store_id = arguments.get("store_id") or None
            if isinstance(listing_id, str) and not listing_id.strip():
                listing_id = None
            if isinstance(store_id, str) and not store_id.strip():
                store_id = None
            return tools.get_listing(product_id, store_id=store_id, listing_id=listing_id)
        if name == "inspect_cart":
            return tools.inspect_cart()
        raise ValueError("Unknown tool: " + str(name))

    def read_answer(self, answer, inputs=None):
        if isinstance(answer, list):
            text = self._text_content(answer)
            try:
                return ClaudeAnswer.model_validate_json(text)
            except (TypeError, ValueError, ValidationError) as exc:
                raise RuntimeError("Claude returned invalid shopping JSON") from exc

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
        # NL tasks require the model to declare its interpreted constraints + ranking rule.
        if status != "clarification_needed" and inputs is not None and inputs.ranking_rule is None:
            if (
                not isinstance(decision.get("constraints"), list)
                or decision.get("ranking_rule") not in {
                    "lowest_price", "highest_rating", "highest_rating_then_reviews", "none",
                }
            ):
                raise ClaudeResponseError(
                    answer.get("stop_reason"), content, "missing interpreted constraints or ranking rule",
                )
            try:
                constraints = [Constraint.model_validate(row) for row in decision["constraints"]]
            except (TypeError, ValidationError) as exc:
                raise ClaudeResponseError(
                    answer.get("stop_reason"), content, f"invalid constraint: {exc}",
                ) from exc
            if not any(row.hard and row.attribute == "category" for row in constraints):
                raise ClaudeResponseError(answer.get("stop_reason"), content, "missing category constraint")
        return decision

    @staticmethod
    def _text_content(content: list[dict]) -> str:
        text = "".join(
            part.get("text", "")
            for part in content
            if part.get("type") == "text"
        ).strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text).strip()
        return text

    @staticmethod
    def normalize_constraints(constraints, listings):
        """Coerce constraint value types to match observed listing fields (verification only)."""
        normalized = []
        for constraint in constraints:
            observed = next(
                (value for item in listings if (value := field_value(item, constraint.attribute)) is not None),
                None,
            )
            value = constraint.value
            if isinstance(value, str) and isinstance(observed, bool) and value.casefold() in {"true", "false"}:
                value = value.casefold() == "true"
            elif isinstance(value, str) and isinstance(observed, (int, float)) and not isinstance(observed, bool):
                try:
                    value = type(observed)(value)
                except ValueError:
                    pass
            normalized.append(constraint.model_copy(update={"value": value}))
        return normalized

    def finish(self, decision, provider_answer, inputs, tools, products):
        content = provider_answer.get("content", [])
        stop_reason = provider_answer.get("stop_reason")
        response_text = decision["response"].strip()
        diagnostics = {
            "model_status": decision["status"],
            "model_product_id": decision.get("product_id") or None,
            "observed_product_ids": sorted(products),
        }

        if decision["status"] == "clarification_needed":
            return AgentOutput(
                response_text=response_text,
                termination_reason="clarification_needed",
                diagnostics=diagnostics,
            )

        if decision["status"] == "no_valid_product":
            return AgentOutput(
                response_text=response_text,
                termination_reason="no_valid_product",
                diagnostics=diagnostics,
            )

        if decision["status"] != "completed":
            raise ClaudeResponseError(stop_reason, content, "missing or invalid status")

        product_id = decision.get("product_id")
        if not isinstance(product_id, str) or not product_id.strip():
            raise ClaudeResponseError(stop_reason, content, "completed decision missing product_id")

        listing_id = decision.get("listing_id") if isinstance(decision.get("listing_id"), str) else ""
        store_id = decision.get("store_id") if isinstance(decision.get("store_id"), str) else ""
        listing_id = listing_id.strip() or None
        store_id = store_id.strip() or None
        prior = products.get(listing_id) if listing_id else None
        if prior is None:
            prior = products.get(product_id)
        if prior is not None:
            listing_id = listing_id or prior.listing_id
            store_id = store_id or prior.store_id

        if inputs.ranking_rule is None:
            try:
                constraints = [Constraint.model_validate(row) for row in decision["constraints"]]
            except (KeyError, TypeError, ValidationError) as exc:
                raise ClaudeResponseError(stop_reason, content, f"invalid interpreted constraints: {exc}") from exc
            if not any(row.hard for row in constraints):
                raise ClaudeResponseError(stop_reason, content, "no hard constraints for a natural-language task")
            rule = decision.get("ranking_rule")
            if rule not in {"lowest_price", "highest_rating", "highest_rating_then_reviews", "none"}:
                raise ClaudeResponseError(stop_reason, content, "invalid ranking rule")
        else:
            constraints = list(inputs.request.constraints)
            rule = inputs.ranking_rule

        diagnostics["ranking_rule"] = rule
        diagnostics["raw_constraints"] = [row.model_dump(mode="json") for row in constraints]
        diagnostics["listing_id"] = listing_id
        diagnostics["store_id"] = store_id

        # Verify Claude's chosen product against a refreshed listing; do not re-rank it.
        product = tools.get_listing(product_id, store_id=store_id, listing_id=listing_id)
        products[product_id] = product
        if product.listing_id:
            products[product.listing_id] = product
        constraints = self.normalize_constraints(constraints, [product])
        diagnostics["interpreted_constraints"] = [row.model_dump(mode="json") for row in constraints]
        diagnostics["eligible_product_ids"] = (
            [product_id] if eligible(product, constraints) else []
        )

        if product.product.stock < 1 or not eligible(product, constraints):
            return AgentOutput(
                response_text=response_text,
                termination_reason="no_valid_product",
                diagnostics=diagnostics,
            )

        cart = tools.inspect_cart()
        if cart.items:
            raise ClaudeResponseError(stop_reason, content, "cart was not empty before purchase")
        cart = tools.add_to_cart(CartSelection(
            product_id=product_id,
            quantity=1,
            store_id=product.store_id,
            listing_id=product.listing_id,
        ))
        if len(cart.items) != 1 or cart.items[0].product_id != product_id:
            raise ClaudeResponseError(stop_reason, content, "cart verification failed")
        if (
            cart.items[0].quantity != 1
            or not cart.items[0].in_stock
            or cart.items[0].unit_price != product.product.price
        ):
            raise ClaudeResponseError(stop_reason, content, "cart price or stock changed")

        claims = []
        for item in decision.get("claims") or []:
            if not isinstance(item, dict) or "field" not in item or "value" not in item:
                raise ClaudeResponseError(stop_reason, content, "invalid claim entry")
            claims.append(Claim(
                claim_id=f"{product_id}:{item['field']}",
                product_id=product_id,
                field=item["field"],
                value=item["value"],
            ))
        if not claims:
            claims = [Claim(
                claim_id=f"{product_id}:price",
                product_id=product_id,
                field="price",
                value=product.product.price,
            )]

        return AgentOutput(
            selected_product_ids=[product_id],
            selected_listing_ids=[product.listing_id] if product.listing_id else [],
            response_text=response_text,
            claims=claims,
            evidence=verify_claims(product, claims),
            termination_reason="completed",
            diagnostics=diagnostics,
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
