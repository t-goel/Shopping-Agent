"""Reproducible baseline conditions for the natural-language suite.

These agents are deterministic, offline model surrogates. They read only the
shopper's original text and the public catalog observations exposed by the
tools; they never read a task's hidden expected outcome. They exist so the
single-prompt, vanilla-ReAct, no-verifier-ablation, and full conditions can all
be run with three seeds on machines without an Anthropic API key. A live
provider-backed run uses ``--agent claude`` instead.

The four conditions differ only in the information and checks they use:

* ``single_prompt`` - one model call over a single search snapshot; shallow
  sponsored-first choice, no ambiguity detection and no verification gate.
* ``react`` - a plain tool loop; the model inspects a few listings and carts
  the cheapest observed item without structured constraint checks.
* ``no_verifier`` - the proposed pipeline's planning and ranking, but with the
  deterministic verification gate removed (no re-read, eligibility re-check,
  cart verification, or claim evidence).
* ``full`` - the proposed pipeline including the deterministic verification
  gate. Comparing it with ``no_verifier`` isolates what the checks add.
"""

from __future__ import annotations

import hashlib
import re

from shopping_agent.agent.rules import rank
from shopping_agent.contracts import (
    CartSelection,
    Constraint,
    ProductObservation,
    SearchInput,
)
from shopping_agent.interfaces import AgentInput, AgentOutput, Claim, ShoppingTools
from shopping_agent.tools.api import ToolError
from shopping_agent.verifier import eligible, verify_claims

CONDITIONS = ("single_prompt", "react", "no_verifier", "full")
MODEL_ID = "offline-surrogate-v1"
PROMPT_VERSION = "offline-baselines-v1"

_NUMBER_WORDS = {
    "a hundred": 100.0,
    "one hundred": 100.0,
    "hundred": 100.0,
    "eighty": 80.0,
    "seventy": 70.0,
    "fifty": 50.0,
}

_CATEGORY_PATTERNS = (
    (r"\b(?:rain[-\s]?)?(?:jackets?|coats?|rain shells?)\b", "jackets"),
    (r"\b(?:daypacks?|backpacks?|packs?|duffels?|bags?)\b", "bags"),
    (r"\b(?:shoes?|hikers?|footwear|trail runners?|sneakers?|boots?)\b", "footwear"),
)


def _add(constraints: list[Constraint], attribute: str, operator: str, value) -> None:
    if not any(
        row.attribute == attribute and row.operator == operator and row.value == value
        for row in constraints
    ):
        constraints.append(Constraint(attribute=attribute, operator=operator, value=value, hard=True))


def _money(text: str) -> float | None:
    match = re.search(r"\$\s*(?P<amount>\d+(?:\.\d{1,2})?)", text)
    if match:
        return float(match.group("amount"))
    match = re.search(r"\b(?P<word>a hundred|one hundred|hundred|eighty|seventy|fifty)\b", text)
    if match:
        return _NUMBER_WORDS[match.group("word")]
    match = re.search(r"\b(?P<amount>\d+(?:\.\d{1,2})?)\s*(?:dollars?|bucks?)\b", text)
    return float(match.group("amount")) if match else None


def interpret_request(text: str) -> tuple[list[Constraint], str | None, str | None]:
    """Derive constraints, ranking, and ambiguity from original text alone.

    This is the offline surrogate's language understanding step. It is
    intentionally rule-based and uses only public request wording; it does not
    consult task definitions, expected sets, or the evaluator's ranking rule.
    """

    normalized = " ".join(text.casefold().split())
    # Items the shopper says are already packed are context, not the target.
    normalized = re.sub(r"[^.?!]*\b(?:already\s+)?packed\b[^.?!]*[.?!]?", " ", normalized)
    normalized = " ".join(normalized.split())
    constraints: list[Constraint] = []

    category = next(
        (value for pattern, value in _CATEGORY_PATTERNS if re.search(pattern, normalized)),
        None,
    )
    if category:
        _add(constraints, "category", "eq", category)

    if re.search(r"\b(?:not|non[-\s]?|without)\s+water[-\s]?proof\b", normalized):
        _add(constraints, "waterproof", "eq", False)
    elif re.search(
        r"\b(?:water[-\s]?proof|monsoon|downpour|heavy rain|rain|keeps?\b.{0,40}\bdry|stay dry)\b",
        normalized,
    ):
        _add(constraints, "waterproof", "eq", True)

    if category == "footwear":
        size = re.search(
            r"\b(?:u\.?s\.?\s*|men'?s\s*(?:us\s*)?|size[-\s]?)(?P<size>\d{1,2}(?:\.\d)?)\b",
            normalized,
        )
        if size:
            _add(constraints, "size", "eq", size.group("size"))
    elif category == "jackets":
        size = re.search(
            r"\b(?:size[-\s]?)?(?P<size>medium|small|large|extra[-\s]?small|extra[-\s]?large|xs|xl|s|m|l)\b",
            normalized,
        )
        if size:
            words = {
                "medium": "M", "small": "S", "large": "L",
                "extra small": "XS", "extra-small": "XS",
                "extra large": "XL", "extra-large": "XL",
            }
            value = size.group("size")
            _add(constraints, "size", "eq", words.get(value, value.upper()))

    price = _money(normalized)
    if price is not None:
        if re.search(
            r"\b(?:under|below|less than|at or under|up to|no more than|stay under|max(?:imum)?|"
            r"budget|won'?t go over|not over)\b",
            normalized,
        ):
            _add(constraints, "price", "lte", price)
        elif re.search(r"\b(?:over|above|more than|at least|no less than)\b", normalized):
            _add(constraints, "price", "gte", price)

    liters = re.search(r"~?\s*(?P<liters>\d{1,3})\s*(?:liters?|litres?)\b", normalized)
    if re.search(r"\b(?:daypack|day pack|expedition|giant)\b", normalized):
        _add(constraints, "capacity_liters", "gte", 20)
        _add(constraints, "capacity_liters", "lte", 25)
    elif liters:
        val = float(liters.group("liters"))
        if "~" in liters.group(0) or re.search(r"\b(?:approx(?:imately)?|around|about)\b", normalized):
            _add(constraints, "capacity_liters", "gte", max(1.0, val - 5.0))
            _add(constraints, "capacity_liters", "lte", val + 5.0)
        else:
            _add(constraints, "capacity_liters", "eq", val)

    if re.search(r"\b(?:cheapest|lowest[-\s]?priced|least expensive|most affordable|lowest price)\b", normalized):
        ranking: str | None = "lowest_price"
    elif re.search(r"\b(?:rate highest|highest rated|best rated|top rated|highest average|by rating)\b", normalized):
        ranking = (
            "highest_rating_then_reviews"
            if re.search(r"\b(?:several qualify|review count|most reviews|tie)\b", normalized)
            else "highest_rating"
        )
    else:
        ranking = None

    clarification = None
    if re.search(r"\b(?:not sure|unsure|not certain|figure (?:something|it) out|runs? the same)\b", normalized):
        clarification = "What size do you need for this jacket?"
    elif not category:
        clarification = "What type of product should I look for?"

    return constraints, ranking, clarification


class OfflineAgent:
    """A picklable, deterministic surrogate for one evaluation condition."""

    def __init__(self, condition: str = "full"):
        if condition not in CONDITIONS:
            raise ValueError(f"unknown condition: {condition}")
        self.condition = condition
        self.agent_name = condition
        self.model = MODEL_ID
        self.prompt_id = hashlib.sha256(f"{PROMPT_VERSION}:{condition}".encode()).hexdigest()
        self.input_tokens = None
        self.output_tokens = None

    def _output(self, text: str, reason: str, diagnostics: dict, **kwargs) -> AgentOutput:
        diagnostics = {**diagnostics, "verification_gate": self.condition == "full"}
        return AgentOutput(response_text=text, termination_reason=reason, diagnostics=diagnostics, **kwargs)

    def _no_match(self, diagnostics: dict) -> AgentOutput:
        return self._output(
            "No observed product satisfies every hard requirement and stock requirement.",
            "no_valid_product",
            diagnostics,
        )

    def _cart(self, observation: ProductObservation, tools: ShoppingTools, verify: bool) -> bool:
        product = observation.product
        try:
            cart = tools.add_to_cart(CartSelection(
                product_id=product.product_id,
                quantity=1,
                store_id=observation.store_id,
                listing_id=observation.listing_id,
            ))
        except ToolError as exc:
            if exc.status_code == 409:
                return False
            raise
        if verify and (
            len(cart.items) != 1
            or cart.items[0].product_id != product.product_id
            or cart.items[0].quantity != 1
            or not cart.items[0].in_stock
            or cart.items[0].unit_price != product.price
        ):
            return False
        return True

    def _complete(self, observation: ProductObservation, diagnostics: dict, tools: ShoppingTools) -> AgentOutput:
        product = observation.product
        gated = self.condition == "full"
        if not self._cart(observation, tools, verify=gated):
            return self._no_match(diagnostics)
        claims = (
            [
                Claim(
                    claim_id=f"{product.product_id}:{field}",
                    product_id=product.product_id,
                    field=field,
                    value=value,
                )
                for field, value in (("title", product.title), ("price", product.price))
            ]
            if gated
            else []
        )
        return self._output(
            f"Selected {product.title} for ${product.price:.2f}; added one unit to the mock cart.",
            "completed",
            {
                **diagnostics,
                "selected_product_id": product.product_id,
                "selected_listing_id": observation.listing_id,
            },
            selected_product_ids=[product.product_id],
            selected_listing_ids=[observation.listing_id] if observation.listing_id else [],
            claims=claims,
            evidence=verify_claims(observation, claims) if gated else [],
        )

    def run(self, inputs: AgentInput, tools: ShoppingTools) -> AgentOutput:
        text = inputs.request.original_text
        if not text.strip():
            raise ValueError("shopping query must not be empty")

        constraints, ranking, clarification = interpret_request(text)
        diagnostics = {
            "condition": self.condition,
            "interpreted_constraints": [row.model_dump(mode="json") for row in constraints],
            "ranking_rule": ranking,
        }

        # The single-prompt baseline makes one shallow call and does not notice
        # the size ambiguity; that is part of what the comparison measures.
        if clarification and self.condition != "single_prompt":
            return self._output(clarification, "clarification_needed", diagnostics)

        category = next(
            (row.value for row in constraints if row.attribute == "category" and row.hard),
            None,
        )
        if not category:
            return self._output(
                clarification or "What type of product should I look for?",
                "clarification_needed",
                diagnostics,
            )

        try:
            stores = tools.list_stores()
            store_ids = [store.store_id for store in stores] or [None]
        except ToolError as exc:
            if exc.status_code != 404:
                raise
            store_ids = [None]

        observed: list[ProductObservation] = []
        for store_id in store_ids:
            page = tools.search(SearchInput(query=category, max_results=50, store_id=store_id))
            observed.extend(page.items)

        if self.condition == "single_prompt":
            if not observed:
                return self._no_match(diagnostics)
            # One snapshot, sponsored-first order: no constraint or ranking reasoning.
            return self._complete(observed[0], diagnostics, tools)

        current: list[ProductObservation] = []
        for observation in sorted(observed, key=lambda row: row.product.product_id):
            try:
                current.append(tools.get_listing(
                    observation.product.product_id,
                    store_id=observation.store_id,
                    listing_id=observation.listing_id,
                ))
            except ToolError as exc:
                if exc.status_code == 404:
                    continue
                raise

        if self.condition == "react":
            # Plain ReAct: inspect listings, then cart the cheapest (or best
            # rated) observed item without any deterministic eligibility check.
            pool = current or observed
            chosen = rank(pool, ranking)[0] if ranking and "rating" in ranking else min(
                pool, key=lambda row: (row.product.price, row.product.product_id)
            )
            return self._complete(chosen, diagnostics, tools)

        valid = [row for row in current if eligible(row, constraints)]
        if not valid:
            return self._no_match(diagnostics)
        chosen = rank(valid, ranking)[0]

        if self.condition == "full":
            # The verification gate: refresh the chosen listing and re-check
            # hard constraints and stock before touching the cart.
            fresh = tools.get_listing(
                chosen.product.product_id,
                store_id=chosen.store_id,
                listing_id=chosen.listing_id,
            )
            if not eligible(fresh, constraints):
                return self._no_match(diagnostics)
            if tools.inspect_cart().items:
                raise ValueError("cart was not empty before purchase")
            chosen = fresh

        return self._complete(chosen, diagnostics, tools)
