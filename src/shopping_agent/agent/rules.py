"""Structured-request rules baseline; no natural-language parser or evaluator-answer access."""

from shopping_agent.contracts import CartSelection, ProductObservation, SearchInput
from shopping_agent.interfaces import AgentInput, AgentOutput, Claim, ShoppingTools
from shopping_agent.tools.api import ToolError
from shopping_agent.verifier import eligible, verify_claims


def rank(observations: list[ProductObservation], rule: str | None) -> list[ProductObservation]:
    """Sort candidate observations by the task ranking rule, breaking ties by product ID."""

    def sorting_key(observation: ProductObservation):
        product = observation.product

        if rule == "lowest_price":
            return product.price, product.product_id

        if rule in {"highest_rating", "highest_rating_then_reviews"}:
            if product.reviews:
                average_rating = sum(r.rating for r in product.reviews) / len(product.reviews)
            else:
                average_rating = -1.0

            review_tie = -len(product.reviews) if rule == "highest_rating_then_reviews" else 0
            return -average_rating, review_tie, product.product_id

        return 0, product.product_id

    return sorted(observations, key=sorting_key)


def _listing_key(observation: ProductObservation) -> str:
    if observation.listing_id:
        return observation.listing_id
    return observation.product.product_id


class RulesAgent:
    def run(self, inputs: AgentInput, tools: ShoppingTools) -> AgentOutput:
        request = inputs.request

        if inputs.ranking_rule is None and not request.constraints and not request.clarification_needed:
            raise ValueError("rules pilot requires structured Surface A input")

        if request.clarification_needed:
            return AgentOutput(
                response_text=request.clarification_needed,
                termination_reason="clarification_needed",
            )

        categories = [
            constraint.value
            for constraint in request.constraints
            if constraint.hard
            and constraint.attribute == "category"
            and constraint.operator == "eq"
            and isinstance(constraint.value, str)
        ]

        if not categories:
            raise ValueError("rules pilot requires an explicit category constraint")

        store_ids: list[str | None]
        try:
            stores = tools.list_stores()
            store_ids = [store.store_id for store in stores]
        except ToolError as exc:
            if exc.status_code != 404:
                raise
            store_ids = [None]

        results_items: list[ProductObservation] = []
        for store_id in store_ids:
            page = tools.search(
                SearchInput(query=categories[0], max_results=50, store_id=store_id)
            )
            if len(page.items) == 50:
                raise ValueError("search may be truncated; cannot establish a complete candidate set")
            results_items.extend(page.items)

        # Re-read every result, including initial nonmatches, so a price drop can create a winner.
        current = []
        for observation in sorted(results_items, key=lambda obs: _listing_key(obs)):
            try:
                latest = tools.get_listing(
                    observation.product.product_id,
                    store_id=observation.store_id,
                    listing_id=observation.listing_id,
                )
            except ToolError as exc:
                if exc.status_code == 404:
                    continue
                raise

            if eligible(latest, request.constraints):
                current.append(latest)

        while current:
            candidate = rank(current, inputs.ranking_rule)[0]
            candidate_key = _listing_key(candidate)

            try:
                latest = tools.get_listing(
                    candidate.product.product_id,
                    store_id=candidate.store_id,
                    listing_id=candidate.listing_id,
                )
            except ToolError as exc:
                if exc.status_code != 404:
                    raise
                current = [item for item in current if _listing_key(item) != candidate_key]
                continue

            current = [item for item in current if _listing_key(item) != candidate_key]

            if not eligible(latest, request.constraints):
                continue

            current.append(latest)

            if _listing_key(rank(current, inputs.ranking_rule)[0]) != candidate_key:
                continue

            selection = CartSelection(
                product_id=latest.product.product_id,
                quantity=1,
                store_id=latest.store_id,
                listing_id=latest.listing_id,
            )
            try:
                cart = tools.add_to_cart(selection)
            except ToolError as exc:
                if exc.status_code == 409:
                    current = [item for item in current if _listing_key(item) != candidate_key]
                    continue
                raise

            product = latest.product

            if (
                len(cart.items) != 1
                or cart.items[0].product_id != product.product_id
                or cart.items[0].quantity != 1
                or not cart.items[0].in_stock
                or cart.items[0].unit_price != product.price
            ):
                return AgentOutput(
                    response_text="Cart changed after verification.",
                    termination_reason="unrecoverable_failure",
                )

            claims = [
                Claim(
                    claim_id=f"{product.product_id}:{field}",
                    product_id=product.product_id,
                    field=field,
                    value=value,
                )
                for field, value in (("title", product.title), ("price", product.price))
            ]

            listing_ids = [latest.listing_id] if latest.listing_id else []
            return AgentOutput(
                selected_product_ids=[product.product_id],
                selected_listing_ids=listing_ids,
                response_text=f"Selected {product.title} for ${product.price:.2f}; added one unit to the mock cart.",
                claims=claims,
                evidence=verify_claims(latest, claims),
                termination_reason="completed",
            )

        return AgentOutput(
            response_text="No observed product satisfies every hard constraint and stock requirement.",
            termination_reason="no_valid_product",
        )
