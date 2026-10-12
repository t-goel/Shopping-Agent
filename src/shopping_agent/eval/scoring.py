"""Evaluator-only scoring from final live state, never agent-reported success."""
from shopping_agent.contracts import Product, TaskDefinition
from shopping_agent.example_checks import matches
from shopping_agent.interfaces import AgentOutput


def score(task: TaskDefinition, output: AgentOutput, snapshot: dict) -> tuple[bool, int, int]:
    products = {key: Product.model_validate(value) for key, value in snapshot["products"].items()}
    hard = [c for c in task.request.constraints if c.hard]
    selected = output.selected_product_ids
    satisfied = sum(
        bool(selected) and all(pid in products and matches(products[pid], c) for pid in selected)
        for c in hard
    )
    cart = snapshot["cart"]["items"]
    if output.termination_reason in {"timeout", "max_tool_calls_exceeded", "unrecoverable_failure"}:
        return False, satisfied, len(hard)
    if task.expected.kind == "clarification":
        success = (output.termination_reason == "clarification_needed" and not selected and not cart
                   and task.expected.question_contains.casefold() in output.response_text.casefold())
        return success, satisfied, len(hard)
    candidates = [p for p in products.values()
                  if p.stock > 0 and all(matches(p, c) for c in hard)]
    if task.expected.kind == "no_valid_product":
        return (output.termination_reason == "no_valid_product" and not candidates
                and not selected and not cart), satisfied, len(hard)
    if task.ranking_rule == "lowest_price" and candidates:
        best = min(p.price for p in candidates)
        candidates = [p for p in candidates if p.price == best]
    elif task.ranking_rule == "highest_rating" and candidates:
        def rating(p):
            return sum(r.rating for r in p.reviews) / len(p.reviews) if p.reviews else -1
        best = max(rating(p) for p in candidates)
        candidates = [p for p in candidates if rating(p) == best]
    valid = {p.product_id for p in candidates} & set(task.expected.valid_product_ids)
    success = (output.termination_reason == "completed" and len(selected) == 1
               and selected[0] in valid and len(cart) == 1
               and cart[0]["product_id"] == selected[0] and cart[0]["quantity"] == 1
               and cart[0]["in_stock"] and cart[0]["unit_price"] == products[selected[0]].price
               and snapshot["cart"]["total"] == products[selected[0]].price)
    return success, satisfied, len(hard)
