"""Structured-request rules baseline; no natural-language parser or oracle access."""
from shopping_agent.contracts import CartSelection, SearchInput
from shopping_agent.interfaces import AgentInput, AgentOutput, Claim, ShoppingTools
from shopping_agent.tools.api import ToolError
from shopping_agent.verifier import eligible, verify_claims


def rank(observations, rule):
    def key(observation):
        p = observation.product
        score = p.price if rule == "lowest_price" else -(
            sum(r.rating for r in p.reviews) / len(p.reviews) if p.reviews else -1
        ) if rule == "highest_rating" else 0
        return score, p.product_id
    return sorted(observations, key=key)


class RulesAgent:
    def run(self, inputs: AgentInput, tools: ShoppingTools) -> AgentOutput:
        request = inputs.request
        if request.clarification_needed:
            return AgentOutput(response_text=request.clarification_needed,
                               termination_reason="clarification_needed")
        # Search the complete tiny category rather than translating all constraints into keywords.
        categories = [c.value for c in request.constraints
                      if c.hard and c.attribute == "category" and c.operator == "eq"
                      and isinstance(c.value, str)]
        if not categories:
            raise ValueError("rules pilot requires an explicit category constraint")
        results = tools.search(SearchInput(query=categories[0], max_results=50))
        if len(results.items) == 50:
            raise ValueError("search may be truncated; cannot establish a complete candidate set")
        # Re-read every result, including initial nonmatches, so a price drop can create a winner.
        current = []
        for observation in sorted(results.items, key=lambda o: o.product.product_id):
            try:
                latest = tools.get_listing(observation.product.product_id)
            except ToolError as exc:
                if exc.status_code == 404:
                    continue
                raise
            if eligible(latest, request.constraints):
                current.append(latest)
        for candidate in rank(current, inputs.ranking_rule):
            latest = tools.get_listing(candidate.product.product_id)
            if not eligible(latest, request.constraints):
                continue
            try:
                cart = tools.add_to_cart(CartSelection(product_id=latest.product.product_id, quantity=1))
            except ToolError as exc:
                if exc.status_code == 409:
                    continue
                raise
            p = latest.product
            if (len(cart.items) != 1 or cart.items[0].product_id != p.product_id
                    or cart.items[0].quantity != 1 or not cart.items[0].in_stock
                    or cart.items[0].unit_price != p.price):
                return AgentOutput(response_text="Cart changed after verification.",
                                   termination_reason="unrecoverable_failure")
            claims = [Claim(claim_id=f"{p.product_id}:{field}", product_id=p.product_id,
                            field=field, value=value)
                      for field, value in (("title", p.title), ("price", p.price))]
            return AgentOutput(selected_product_ids=[p.product_id],
                               response_text=f"Selected {p.title} for ${p.price:.2f}; added one unit to the mock cart.",
                               claims=claims, evidence=verify_claims(latest, claims),
                               termination_reason="completed")
        return AgentOutput(response_text="No observed product satisfies every hard constraint and stock requirement.",
                           termination_reason="no_valid_product")
