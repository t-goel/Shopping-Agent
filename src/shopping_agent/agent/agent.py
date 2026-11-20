"""A Claude shopping agent."""

import hashlib
import json
import os
import re
from dataclasses import dataclass, field

import requests
from pydantic import ValidationError

from shopping_agent.agent.request_parser import parse_request
from shopping_agent.agent.rules import rank
from shopping_agent.comparison import canonical_size
from shopping_agent.contracts import (
    CartSelection,
    ClaudeAnswer,
    Constraint,
    Operator,
    ProductObservation,
    RequestInterpretation,
    SearchInput,
    ShoppingRequest,
    listing_id_for,
)
from shopping_agent.interfaces import AgentInput, AgentOutput, Claim, ShoppingTools
from shopping_agent.tools.api import ToolError
from shopping_agent.tools.budget import BudgetExceeded, verification_scope
from shopping_agent.verifier import (
    eligible,
    field_value,
    verification_failure_reason,
    verify_claims,
)

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
            "Get current details for one product listing. "
            "A listing_id has the format 'store_id:product_id' (e.g. 'trailworks-direct:ridge-shell'); "
            "a product_id is just the product part (e.g. 'ridge-shell'). "
            "In multi-store mode, pass listing_id alone OR product_id together with store_id. "
            "Do NOT pass a bare product_id without store_id on multi-store catalogs."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "product_id": {
                    "type": "string",
                    "description": "The product identifier (e.g. 'ridge-shell'). Requires store_id on multi-store catalogs.",
                },
                "store_id": {
                    "type": "string",
                    "description": "Store identifier (e.g. 'trailworks-direct'). Required with product_id on multi-store catalogs.",
                },
                "listing_id": {
                    "type": "string",
                    "description": "Store-specific listing identifier in 'store_id:product_id' format (e.g. 'trailworks-direct:ridge-shell'). When provided, product_id and store_id are ignored.",
                },
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
 "product_id":"bare product id (e.g. 'ridge-shell') or empty string",
 "listing_id":"store-specific 'store_id:product_id' (e.g. 'trailworks-direct:ridge-shell') when known, else empty string",
 "store_id":"store id when known, else empty string",
 "response":"short explanation or question",
 "constraints":[{"attribute":"category","operator":"eq","value":"jackets","hard":true}],
 "ranking_rule":"lowest_price|highest_rating|highest_rating_then_reviews|none",
 "claims":[{"field":"price","value":89}]}
In multi-store mode, pass the store-specific listing_id ('store_id:product_id') so the chosen
store offering is purchased.
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
A final choice is re-verified against a refreshed listing before it is added to the
cart. If that verification fails (for example, the price rose above your budget or
the item went out of stock), you will receive a verification_failure observation
with the exact reason. Treat it as a new observation: pick a different eligible,
in-stock candidate you have already observed, or refresh one listing, and return
another final JSON decision within your remaining tool budget. Do not repeat a
rejected product, and do not switch to no_valid_product while another viable
candidate remains.
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
  "ranking_rule": "lowest_price|highest_rating|highest_rating_then_reviews|none"
}

Extract only constraints that are stated or clearly implied. Use hard=true
only for requirements; put preferences in preferences. Never invent product
facts. If the request does not identify a product category, set
clarification_needed to a concise question. Use the original request exactly.

Supported product attributes include: category, waterproof, size, price, capacity_liters.
Categories are: jackets, bags, footwear.
For approximate quantities (such as "~30 liter", "approximately 30 liters", or "daypack sized"),
handle them with realistic bounds (for example, capacity_liters gte 25 and lte 35 for ~30L,
or gte 20 and lte 25 for daypack) instead of strict equality.
If several products qualify and rating or review tie-breaking is mentioned, use ranking_rule "highest_rating_then_reviews".
If the shopper indicates uncertainty about sizing (e.g. unsure if brand sizing fits), set clarification_needed to ask what size is needed.
"""


class ClaudeResponseError(RuntimeError):
    """Preserve the provider's stopping point and final text for failed trials."""

    def __init__(self, reason, content, problem):
        final_text = "".join(block.get("text", "") for block in content if block.get("type") == "text")
        super().__init__(
            f"Claude final response invalid ({problem}); stop_reason={reason!r}; final_text={final_text!r}"
        )


@dataclass
class VerificationRejection:
    """A completed decision whose chosen product failed the deterministic gate.

    Returned by ``finish`` instead of a terminal ``AgentOutput`` so the ReAct loop can
    feed the reason back as a fresh observation and let the model choose a runner-up.
    """

    product_id: str
    reason: str
    response_text: str
    diagnostics: dict = field(default_factory=dict)
    price: float | None = None
    stock: int | None = None
    listing_id: str | None = None
    matched_observation: bool = True

    def as_dict(self) -> dict:
        """Bounded record of one rejection, including how the gate reached its verdict."""
        return {
            "product_id": self.product_id,
            "reason": self.reason,
            "response_text": self.response_text,
            "observed_price": self.price,
            "observed_stock": self.stock,
            "gate_input_source": self.diagnostics.get("gate_input_source"),
            "corrected_constraints": self.diagnostics.get("corrected_constraints", []),
            "ambiguous_product_id": self.diagnostics.get("ambiguous_product_id"),
        }


@dataclass
class ObservationCache:
    """Listing observations from one run, keyed by listing identity.

    A bare product ID is not a listing key. On a multi-store catalog the same
    product is offered by several stores, so caching observations by product ID
    lets one store's variant overwrite another's. Keys are listing IDs when the
    catalog has them, and bare product IDs only when the response carried no
    listing identity (flat single-store catalogs).
    """

    by_listing: dict[str, ProductObservation] = field(default_factory=dict)
    listings_for_product: dict[str, list[str]] = field(default_factory=dict)

    @staticmethod
    def key(observation: ProductObservation) -> str:
        return observation.listing_id or observation.product.product_id

    def record(self, observation: ProductObservation) -> None:
        key = self.key(observation)
        self.by_listing[key] = observation
        known = self.listings_for_product.setdefault(observation.product.product_id, [])
        if key not in known:
            known.append(key)

    def get(self, key: str | None) -> ProductObservation | None:
        return self.by_listing.get(key) if key else None

    def candidates_for(self, product_id: str | None) -> list[str]:
        """Every listing key observed for a product, in first-seen order."""
        if not product_id:
            return []
        known = self.listings_for_product.get(product_id)
        if known:
            return list(known)
        return [product_id] if product_id in self.by_listing else []

    def resolve(self, product_id: str | None, listing_id: str | None) -> tuple[str | None, list[str]]:
        """Return the one observed key for a proposed pick, else the ambiguous candidates."""
        if listing_id and listing_id in self.by_listing:
            return listing_id, []
        candidates = self.candidates_for(product_id)
        if listing_id:
            candidates = [key for key in candidates if key == listing_id]
        if len(candidates) == 1:
            return candidates[0], []
        return None, candidates

    def observations(self) -> list[ProductObservation]:
        return list(self.by_listing.values())

    def listing_ids(self) -> list[str]:
        return sorted(self.by_listing)


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
        # Provider calls actually made this trial: interpretation + every ReAct turn.
        self.model_turns = 0
        self.url = "https://api.anthropic.com/v1/messages"

    def interpret_query(self, query: str) -> RequestInterpretation:
        """Use Claude (or deterministic parser for test keys/offline) to turn free-form language into a validated request."""
        if not query or not query.strip():
            raise ValueError("shopping query must not be empty")
        if not self.api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set")

        if hasattr(self, "interpretation") and self.interpretation is not None:
            return self.interpretation

        if self.api_key == "test-key":
            req, rule = parse_request(query)
            return RequestInterpretation(request=req, ranking_rule=rule)

        # The live interpretation call is a model turn; the test-key parser is not.
        self.model_turns += 1
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
        self.model_turns = 0
        if inputs.request.clarification_needed:
            return AgentOutput(
                response_text=inputs.request.clarification_needed,
                termination_reason="clarification_needed",
                diagnostics={
                    "model_turns": self.model_turns,
                    "gate_input_source": "none",
                },
            )
        if not self.api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set")

        is_nl = (inputs.ranking_rule is None) or (
            not inputs.request.constraints and not inputs.request.clarification_needed
        )
        if is_nl:
            interpretation = self.interpret_query(inputs.request.original_text)
            active_constraints = list(interpretation.request.constraints)
            active_ranking_rule = interpretation.ranking_rule
            clarification_needed = interpretation.request.clarification_needed
            preferences = list(interpretation.request.preferences)
        else:
            active_constraints = list(inputs.request.constraints)
            active_ranking_rule = inputs.ranking_rule
            clarification_needed = inputs.request.clarification_needed
            preferences = list(inputs.request.preferences)

        # Only treat a capacity eq as approximate when the request actually says so.
        approximate_capacity = bool(re.search(
            r"~|approx(?:imately)?\b|about\b|around\b|roughly\b",
            inputs.request.original_text, re.IGNORECASE,
        ))

        diagnostics = {
            "extracted_constraints": [c.model_dump(mode="json") for c in active_constraints],
            "interpreted_ranking_rule": active_ranking_rule,
        }

        if clarification_needed:
            diagnostics["model_status"] = "clarification_needed"
            diagnostics["model_turns"] = self.model_turns
            diagnostics["gate_input_source"] = "none"
            return AgentOutput(
                response_text=clarification_needed,
                termination_reason="clarification_needed",
                diagnostics=diagnostics,
            )

        messages = [{
            "role": "user",
            "content": json.dumps({
                "request": {
                    "original_text": inputs.request.original_text,
                    "constraints": [c.model_dump(mode="json") for c in active_constraints],
                    "preferences": preferences,
                },
                "ranking_rule": active_ranking_rule,
            }),
        }]
        observations = ObservationCache()
        correction_used = False
        last_response_error = None
        rejections: list[VerificationRejection] = []

        for turn in range(self.max_turns):
            # Count every ReAct model call, including subclassed ask_claude stubs.
            self.model_turns += 1
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

                outcome = self.finish(
                    decision,
                    answer,
                    inputs,
                    tools,
                    observations,
                    active_constraints=active_constraints,
                    active_ranking_rule=active_ranking_rule,
                    approximate_capacity=approximate_capacity,
                )
                if isinstance(outcome, VerificationRejection):
                    rejections.append(outcome)
                    if answer.get("content"):
                        messages.append({"role": "assistant", "content": answer["content"]})
                    turns_remaining = self.max_turns - turn - 1
                    if turns_remaining <= 0:
                        # No future turn can consume another observation. Stop asking
                        # the model and use a tool-only deterministic runner-up instead.
                        break
                    messages.append({
                        "role": "user",
                        "content": self._verification_observation(
                            outcome,
                            observations,
                            rejected_ids=[item.product_id for item in rejections],
                            turns_remaining=turns_remaining,
                        ),
                    })
                    continue

                if rejections:
                    outcome.diagnostics["verification_rejections"] = [
                        rejection.as_dict() for rejection in rejections
                    ]
                    if outcome.termination_reason == "completed":
                        outcome.diagnostics["recovered_after_rejection"] = True
                outcome.diagnostics["model_turns"] = self.model_turns
                last_response_error = None
                return outcome

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
                            observations.record(item)
                    elif block["name"] == "get_listing":
                        observations.record(result)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block["id"],
                        "content": self._tool_content(result),
                    })

            messages.append({"role": "assistant", "content": answer["content"]})
            messages.append({"role": "user", "content": tool_results})

        if rejections:
            # The gate rejected every proposed product and no model turn remains to
            # repair it. Fall back to a deterministic re-rank (tool calls only) so the
            # remaining public tool budget cannot be stranded by turn exhaustion.
            last = rejections[-1]
            diagnostics = dict(last.diagnostics)
            diagnostics["verification_rejections"] = [
                rejection.as_dict() for rejection in rejections
            ]
            fallback = self._deterministic_pick(
                observations, rejections, tools, active_constraints, active_ranking_rule,
                diagnostics, approximate_capacity=approximate_capacity,
            )
            if fallback is not None:
                fallback.diagnostics["verification_rejections"] = [
                    rejection.as_dict() for rejection in rejections
                ]
                fallback.diagnostics["recovered_by_deterministic_fallback"] = True
                fallback.diagnostics["model_turns"] = self.model_turns
                return fallback
            diagnostics["model_status"] = "no_valid_product"
            diagnostics["recovery_exhausted"] = True
            diagnostics["deterministic_fallback_exhausted"] = True
            diagnostics["model_turns"] = self.model_turns
            # Still report whether the abstention looks wrong from what was observed.
            diagnostics.update(self._abstention_diagnostics(observations, active_constraints))
            return AgentOutput(
                response_text=(
                    "The selected product failed final verification after a catalog change, "
                    "and no alternative was confirmed within the remaining tool budget."
                ),
                termination_reason="no_valid_product",
                diagnostics=diagnostics,
            )

        if last_response_error is not None:
            raise last_response_error
        raise RuntimeError("Claude used too many turns")

    @staticmethod
    def _candidate_observations(observations: ObservationCache) -> list:
        """Unique observed products, keyed by store listing."""
        seen = set()
        candidates = []
        for observation in observations.observations():
            key = (observation.store_id, observation.product.product_id)
            if key in seen:
                continue
            seen.add(key)
            candidates.append(observation)
        return candidates

    @staticmethod
    def _clarification_hits_unconstrained_attribute(text, constraints, listings) -> bool:
        """True when the question asks about an attribute no hard constraint covers.

        A clarification about such an attribute cannot be answered from the
        request alone, so coercing it into a purchase would guess at an
        unspecified user preference. Questions about attributes the request
        already constrains are candidates for the false-abstention fallback.
        """
        covered = {
            item.attribute.casefold().replace("_", " ")
            for item in constraints if item.hard
        }
        lowered = (text or "").casefold()
        attributes = set()
        for observation in listings:
            attributes.update(observation.product.attributes)
        for attribute in attributes:
            token = str(attribute).casefold().replace("_", " ")
            root = token.split(" ", 1)[0]
            if not root or token in covered or root in covered:
                continue
            if re.search(rf"\b{re.escape(root)}", lowered):
                return True
        return False

    @staticmethod
    def _remaining_tool_calls(tools) -> int | None:
        """Public tool calls still available, or None for unbudgeted tools."""
        max_calls = getattr(tools, "max_calls", None)
        trace = getattr(tools, "trace", None)
        if isinstance(max_calls, int) and isinstance(trace, (list, tuple)):
            return max(0, max_calls - len(trace))
        return None

    def _deterministic_pick(
        self, observations, rejections, tools, constraints, rule, diagnostics,
        approximate_capacity: bool = False,
    ):
        """Re-rank observed candidates and buy the best eligible runner-up.

        Mirrors ``RulesAgent``'s guarded re-rank: drop the rejected product,
        re-rank the remaining observations, refresh the winner and re-check
        eligibility and stock before the cart write. It spends public tool
        calls but no model turn, so verification cannot deadlock a run that
        still has tool budget. Returns None when no runner-up survives.
        """
        rejected_ids = {item.product_id for item in rejections}
        candidates = [
            observation
            for observation in self._candidate_observations(observations)
            if observation.product.product_id not in rejected_ids
        ]
        if not candidates:
            return None
        remaining = self._remaining_tool_calls(tools)
        if remaining is not None and remaining < 3:
            return None

        normalized = self.normalize_constraints(
            constraints or [], candidates, approximate_capacity
        )
        current = rank(
            [item for item in candidates if eligible(item, normalized)], rule
        )
        for candidate in current:
            remaining = self._remaining_tool_calls(tools)
            if remaining is not None and remaining < 3:
                break
            try:
                latest = tools.get_listing(
                    candidate.product.product_id,
                    store_id=candidate.store_id,
                    listing_id=candidate.listing_id,
                )
            except ToolError as exc:
                if exc.status_code == 404:
                    continue
                raise
            except BudgetExceeded:
                return None
            if not eligible(latest, normalized):
                continue
            try:
                cart = tools.inspect_cart()
                if cart.items:
                    return None
                selection = CartSelection(
                    product_id=latest.product.product_id,
                    quantity=1,
                    store_id=latest.store_id,
                    listing_id=latest.listing_id,
                )
                cart = tools.add_to_cart(selection)
            except ToolError as exc:
                if exc.status_code == 409:
                    continue
                raise
            except BudgetExceeded:
                return None
            product = latest.product
            if (
                len(cart.items) != 1
                or cart.items[0].product_id != product.product_id
                or cart.items[0].quantity != 1
                or not cart.items[0].in_stock
                or cart.items[0].unit_price != product.price
            ):
                return None

            claims = [Claim(
                claim_id=f"{product.product_id}:price",
                product_id=product.product_id,
                field="price",
                value=product.price,
            )]
            fallback_diagnostics = dict(diagnostics)
            # Keep model_status as the model's own decision; the fallback is
            # distinguished by termination_reason and selected_by.
            fallback_diagnostics["fallback_status"] = "completed"
            fallback_diagnostics["listing_id"] = latest.listing_id
            fallback_diagnostics["store_id"] = latest.store_id
            fallback_diagnostics["selected_by"] = "deterministic_fallback"
            fallback_diagnostics["model_turns"] = self.model_turns
            return AgentOutput(
                selected_product_ids=[product.product_id],
                selected_listing_ids=[latest.listing_id] if latest.listing_id else [],
                response_text=(
                    f"Selected {product.title} for ${product.price:.2f} using the "
                    + (
                        "best remaining in-stock candidate after final verification failed."
                        if rejections else
                        "best in-stock match for the interpreted request."
                    )
                ),
                claims=claims,
                evidence=verify_claims(latest, claims),
                termination_reason="completed",
                diagnostics=fallback_diagnostics,
            )
        return None

    @staticmethod
    def _abstention_diagnostics(observations: ObservationCache, constraints) -> dict:
        """Record whether an abstention looks false given what the run observed.

        This is an advisory signal for triage, not a re-score: an abstention never
        triggers a live re-read, so the observations behind it may be stale.
        """
        # Compare against listed types first, exactly as the purchase gate would.
        active = Agent.normalize_constraints(
            list(constraints or []), observations.observations()
        )
        matching = [
            key for key, observation in observations.by_listing.items()
            if eligible(observation, active)
        ]
        return {
            "gate_input_source": "observation_cache",
            "false_abstention_candidate": {
                "present": bool(matching),
                "listing_ids": matching,
                "source": "observation_cache",
                "note": (
                    "Observations only, not a fresh catalog read; an abstention never "
                    "forces a live re-read."
                ),
            },
            "observed_listing_ids": observations.listing_ids(),
        }

    @staticmethod
    def _verification_observation(
        rejection: VerificationRejection,
        observations: ObservationCache,
        rejected_ids: list[str],
        turns_remaining: int,
    ) -> str:
        """Render a gate rejection as a tool-like observation for the next ReAct turn."""
        candidates = []
        for observation in observations.observations():
            if rejection.matched_observation and (
                observation.product.product_id == rejection.product_id
                and rejection.listing_id in (None, observation.listing_id)
            ):
                continue
            candidates.append({
                "product_id": observation.product.product_id,
                "listing_id": observation.listing_id,
                "store_id": observation.store_id,
            })

        return json.dumps({
            "type": "verification_failure",
            "message": (
                "Your proposed product failed final verification against the current "
                "listing and was NOT added to the cart. Pick a different eligible, "
                "in-stock candidate from the observed set, or refresh one listing, "
                "then return a new final JSON decision."
            ),
            "rejected_product_id": rejection.product_id,
            "reason": rejection.reason,
            "observed_price": rejection.price,
            "observed_stock": rejection.stock,
            "rejected_product_ids": rejected_ids,
            "observed_candidates": candidates,
            "turns_remaining": turns_remaining,
        })

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
            # Auto-resolve: product_id that looks like a listing_id ("store:product")
            if not listing_id and product_id and ":" in product_id:
                listing_id = product_id
                product_id = None
                store_id = None
            # Auto-resolve: listing_id that looks like a bare product_id (no colon)
            if listing_id and ":" not in listing_id:
                if store_id:
                    listing_id = f"{store_id}:{listing_id}"
                else:
                    if not product_id:
                        product_id = listing_id
                    listing_id = None
            return tools.get_listing(product_id, store_id=store_id, listing_id=listing_id)
        if name == "inspect_cart":
            return tools.inspect_cart()
        if name == "add_to_cart":
            listing_id = arguments.get("listing_id") or None
            product_id = arguments.get("product_id") or None
            store_id = arguments.get("store_id") or None
            quantity = arguments.get("quantity", 1)
            selection = CartSelection(
                product_id=product_id,
                quantity=quantity,
                store_id=store_id,
                listing_id=listing_id,
            )
            return tools.add_to_cart(selection)
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
    def normalize_constraints(
        constraints, listings, approximate_capacity: bool = False, corrections: list | None = None,
    ):
        """Coerce live interpreter values to the types observed in listings.

        Handles booleans/numbers given as strings plus provider-style sizes
        (``medium``, ``9``, ``US 9 men's``). A tolerance is added to a capacity
        ``eq`` only when the request actually describes an approximate amount.
        Only called at verification time; the agent's declared constraints are
        never rewritten for the model. When ``corrections`` is supplied, the
        type coercions applied by the gate are recorded there for the report.
        """
        normalized = []
        for constraint in constraints:
            observed = next(
                (value for item in listings if (value := field_value(item, constraint.attribute)) is not None),
                None,
            )
            value = constraint.value
            tolerance = constraint.tolerance
            corrected = value
            if isinstance(value, str) and isinstance(observed, bool) and value.casefold() in {"true", "false"}:
                corrected = value.casefold() == "true"
            elif isinstance(value, str) and isinstance(observed, (int, float)) and not isinstance(observed, bool):
                try:
                    corrected = type(observed)(value)
                except ValueError:
                    corrected = value
            if corrected is not value and corrections is not None:
                corrections.append({
                    "attribute": constraint.attribute,
                    "from": value,
                    "to": corrected,
                    "observed_type": type(observed).__name__,
                })
            if constraint.attribute == "size":
                observed_size = canonical_size(observed)
                target_size = canonical_size(corrected)
                if observed_size is not None and target_size == observed_size:
                    corrected = observed_size
            if (
                approximate_capacity
                and constraint.attribute == "capacity_liters"
                and constraint.operator == Operator.EQ
                and isinstance(observed, (int, float))
                and not isinstance(observed, bool)
            ):
                # "~30 liters" may be emitted as capacity_liters eq 30; only
                # relax it when the request signalled an approximation.
                tolerance = 5.0 if tolerance is None else tolerance
            normalized.append(constraint.model_copy(update={"value": corrected, "tolerance": tolerance}))
        return normalized

    def finish(
        self,
        decision,
        provider_answer,
        inputs,
        tools,
        observations: ObservationCache,
        active_constraints=None,
        active_ranking_rule=None,
        approximate_capacity: bool = False,
    ):
        content = provider_answer.get("content", [])
        stop_reason = provider_answer.get("stop_reason")
        response_text = decision["response"].strip()
        diagnostics = {
            "model_status": decision["status"],
            "model_product_id": decision.get("product_id") or None,
            "observed_product_ids": sorted(observations.listings_for_product),
            "observed_listing_ids": observations.listing_ids(),
        }
        if active_constraints is not None:
            diagnostics["extracted_constraints"] = [c.model_dump(mode="json") for c in active_constraints]
            diagnostics["interpreted_ranking_rule"] = active_ranking_rule
        if "constraints" in decision and decision["constraints"] is not None:
            diagnostics["model_constraints"] = decision["constraints"]

        if decision["status"] == "clarification_needed":
            # A clarification loop is a false abstention when the products already
            # observed contain an eligible, in-stock match for the interpreted
            # constraints. Downgrade the ask into a deterministic product pick.
            candidates = self._candidate_observations(observations)
            normalized = self.normalize_constraints(
                active_constraints or [], candidates, approximate_capacity
            )
            valid = [item for item in candidates if eligible(item, normalized)]
            if valid:
                diagnostics["false_abstention_candidates"] = [
                    {
                        "product_id": item.product.product_id,
                        "listing_id": item.listing_id,
                        "store_id": item.store_id,
                    }
                    for item in rank(valid, active_ranking_rule)
                ]
                if self._clarification_hits_unconstrained_attribute(
                    response_text, active_constraints or [], candidates
                ):
                    # The question asks about an attribute the request never
                    # constrained: answering it requires the user, not a guess.
                    diagnostics["clarification_preserved_for_unconstrained_attribute"] = True
                else:
                    fallback = self._deterministic_pick(
                        observations, [], tools, active_constraints, active_ranking_rule,
                        diagnostics, approximate_capacity=approximate_capacity,
                    )
                    if fallback is not None:
                        fallback.diagnostics["coerced_from_clarification"] = True
                        fallback.diagnostics["false_abstention_candidates"] = diagnostics[
                            "false_abstention_candidates"
                        ]
                        return fallback
            diagnostics["model_turns"] = self.model_turns
            diagnostics["gate_input_source"] = "none"
            return AgentOutput(
                response_text=response_text,
                termination_reason="clarification_needed",
                diagnostics=diagnostics,
            )

        if decision["status"] == "no_valid_product":
            # Abstentions are checked against observed state only; nothing is re-read.
            diagnostics.update(self._abstention_diagnostics(observations, active_constraints))
            return AgentOutput(
                response_text=response_text,
                termination_reason="no_valid_product",
                diagnostics=diagnostics,
            )

        if decision["status"] != "completed":
            raise ClaudeResponseError(stop_reason, content, "missing or invalid status")

        product_id = decision.get("product_id") if isinstance(decision.get("product_id"), str) else ""
        listing_id = decision.get("listing_id") if isinstance(decision.get("listing_id"), str) else ""
        store_id = decision.get("store_id") if isinstance(decision.get("store_id"), str) else ""
        product_id = product_id.strip() or None
        listing_id = listing_id.strip() or None
        store_id = store_id.strip() or None

        if not product_id and not listing_id:
            raise ClaudeResponseError(stop_reason, content, "completed decision missing product_id")

        # If product_id contains a colon, it was passed as a listing_id ("store_id:product_id")
        if product_id and ":" in product_id:
            inferred_store, bare_product = product_id.split(":", 1)
            listing_id = listing_id or product_id
            store_id = store_id or inferred_store
            product_id = bare_product

        # If listing_id contains no colon:
        if listing_id and ":" not in listing_id:
            if not product_id:
                product_id = listing_id
            # A bare store plus a bare product is that store's listing key.
            listing_id = listing_id_for(store_id, product_id) if store_id else None
        elif not listing_id and store_id and product_id:
            # An explicit store narrows the pick to that store's listing of the product.
            listing_id = listing_id_for(store_id, product_id)

        key, candidates = observations.resolve(product_id, listing_id)
        if key is None and candidates:
            note = (
                f"product_id {product_id!r} is listed by {len(candidates)} stores "
                f"({', '.join(candidates)}); return the listing_id of the variant meant"
            )
            diagnostics.update({
                "gate_input_source": "none",
                "ambiguous_product_id": {
                    "product_id": product_id,
                    "candidate_listing_ids": candidates,
                },
                "verification_rejection": {"product_id": product_id, "reason": note},
            })
            return VerificationRejection(
                product_id=product_id or "",
                reason=note,
                response_text=response_text,
                diagnostics=diagnostics,
                matched_observation=False,  # Keep both variants visible as candidates.
            )

        prior = observations.get(key)
        if prior is not None:
            listing_id = listing_id or prior.listing_id
            store_id = store_id or prior.store_id

        if not product_id and listing_id and ":" in listing_id:
            product_id = listing_id.split(":", 1)[1]

        if active_constraints is not None:
            constraints = list(active_constraints)
            rule = active_ranking_rule
        elif inputs.ranking_rule is None:
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
        # The refresh reads live store state, so a change since the model's observation wins.
        diagnostics["gate_input_source"] = "live_refresh"
        try:
            with verification_scope(tools):
                product = tools.get_listing(product_id, store_id=store_id, listing_id=listing_id)
        except ToolError as exc:
            if exc.status_code != 404:
                raise
            diagnostics["verification_rejection"] = {
                "product_id": product_id,
                "reason": f"{product_id} is no longer listed (HTTP 404)",
            }
            return VerificationRejection(
                product_id=product_id,
                reason=diagnostics["verification_rejection"]["reason"],
                response_text=response_text,
                diagnostics=diagnostics,
            )
        if product.product.product_id:
            product_id = product.product.product_id
        if product.listing_id:
            listing_id = product.listing_id
        if product.store_id:
            store_id = product.store_id
        diagnostics["listing_id"] = listing_id
        diagnostics["store_id"] = store_id
        observations.record(product)
        corrections = []
        constraints = self.normalize_constraints(
            constraints, [product], approximate_capacity, corrections
        )
        diagnostics["corrected_constraints"] = corrections
        diagnostics["interpreted_constraints"] = [row.model_dump(mode="json") for row in constraints]
        diagnostics["eligible_product_ids"] = (
            [product_id] if eligible(product, constraints) else []
        )

        if product.product.stock < 1 or not eligible(product, constraints):
            reason = verification_failure_reason(product, constraints)
            diagnostics["verification_rejection"] = {
                "product_id": product_id,
                "reason": reason,
            }
            # Feed the failure back to the ReAct loop instead of terminating; the
            # model may choose a runner-up within its remaining tool budget.
            return VerificationRejection(
                product_id=product_id,
                reason=reason,
                response_text=response_text,
                diagnostics=diagnostics,
                price=product.product.price,
                stock=product.product.stock,
                listing_id=product.listing_id,
            )

        with verification_scope(tools):
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
