"""Evaluator-only scoring from final live state, never agent-reported success."""

from shopping_agent.contracts import Product, TaskDefinition
from shopping_agent.example_checks import matches
from shopping_agent.interfaces import AgentOutput


def score(task: TaskDefinition, output: AgentOutput, snapshot: dict) -> tuple[bool, int, int]:
    products = {
        key: Product.model_validate(value)
        for key, value in snapshot["products"].items()
    }
    hard_constraints = [c for c in task.request.constraints if c.hard]
    selected = output.selected_product_ids

    satisfied = sum(
        bool(selected) and all(pid in products and matches(products[pid], c) for pid in selected)
        for c in hard_constraints
    )
    cart = snapshot["cart"]["items"]

    if output.termination_reason in {"timeout", "max_tool_calls_exceeded", "unrecoverable_failure"}:
        return False, satisfied, len(hard_constraints)

    if task.expected.kind == "clarification":
        success = (
            output.termination_reason == "clarification_needed"
            and not selected
            and not cart
            and task.expected.question_contains.casefold() in output.response_text.casefold()
        )
        return success, satisfied, len(hard_constraints)

    candidates = [
        product for product in products.values()
        if product.stock > 0 and all(matches(product, c) for c in hard_constraints)
    ]

    if task.expected.kind == "no_valid_product":
        success = (
            output.termination_reason == "no_valid_product"
            and not candidates
            and not selected
            and not cart
        )
        return success, satisfied, len(hard_constraints)

    if task.ranking_rule == "lowest_price" and candidates:
        best_price = min(p.price for p in candidates)
        candidates = [p for p in candidates if p.price == best_price]

    elif task.ranking_rule in {"highest_rating", "highest_rating_then_reviews"} and candidates:
        def average_rating(product: Product) -> float:
            if product.reviews:
                return sum(r.rating for r in product.reviews) / len(product.reviews)
            return -1.0

        best_rating = max(average_rating(p) for p in candidates)
        candidates = [p for p in candidates if average_rating(p) == best_rating]

        if task.ranking_rule == "highest_rating_then_reviews" and len(candidates) > 1:
            most_reviews = max(len(p.reviews) for p in candidates)
            candidates = [p for p in candidates if len(p.reviews) == most_reviews]

    valid_ids = {p.product_id for p in candidates} & set(task.expected.valid_product_ids)

    success = (
        output.termination_reason == "completed"
        and len(selected) == 1
        and selected[0] in valid_ids
        and len(cart) == 1
        and cart[0]["product_id"] == selected[0]
        and cart[0]["quantity"] == 1
        and cart[0]["in_stock"]
        and cart[0]["unit_price"] == products[selected[0]].price
        and snapshot["cart"]["total"] == products[selected[0]].price
    )

    return success, satisfied, len(hard_constraints)
