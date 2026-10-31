"""Evaluator-only scoring from final live state, never agent-reported success."""

from shopping_agent.comparison import matches
from shopping_agent.contracts import Product, TaskDefinition
from shopping_agent.example_checks import average_rating
from shopping_agent.interfaces import AgentOutput


def _rank_products(candidates: list[Product], ranking_rule: str) -> list[Product]:
    if not candidates:
        return candidates

    if ranking_rule == "lowest_price":
        best_price = min(p.price for p in candidates)
        return [p for p in candidates if p.price == best_price]

    if ranking_rule in {"highest_rating", "highest_rating_then_reviews"}:
        best_rating = max(average_rating(p) for p in candidates)
        ranked = [p for p in candidates if average_rating(p) == best_rating]
        if ranking_rule == "highest_rating_then_reviews" and len(ranked) > 1:
            most_reviews = max(len(p.reviews) for p in ranked)
            ranked = [p for p in ranked if len(p.reviews) == most_reviews]
        return ranked

    return candidates


def _listing_product_view(snapshot: dict, listing_id: str) -> Product:
    listing = snapshot["listings"][listing_id]
    product = snapshot["products"][listing["product_id"]]
    return Product(
        product_id=product["product_id"],
        title=product["title"],
        description=product["description"],
        category=product["category"],
        currency=product.get("currency", "USD"),
        seller=product["seller_default"],
        attributes=product["attributes"],
        reviews=product.get("reviews", []),
        image_url=product.get("image_url"),
        price=listing["price"],
        stock=listing["stock"],
        sponsored=listing.get("sponsored", False),
    )


def _score_listings(
    task: TaskDefinition, output: AgentOutput, snapshot: dict
) -> tuple[bool, int, int]:
    hard_constraints = [c for c in task.request.constraints if c.hard]
    selected_listings = list(output.selected_listing_ids)
    if not selected_listings and output.selected_product_ids:
        # Fallback: infer listing from cart when agent only reported product_id.
        cart_listings = [
            item.get("listing_id")
            for item in snapshot["cart"]["items"]
            if item.get("listing_id")
        ]
        selected_listings = [lid for lid in cart_listings if lid]

    views = {
        listing_id: _listing_product_view(snapshot, listing_id)
        for listing_id in snapshot["listings"]
    }

    satisfied = sum(
        bool(selected_listings)
        and all(
            lid in views and matches(views[lid], c) for lid in selected_listings
        )
        for c in hard_constraints
    )
    cart = snapshot["cart"]["items"]

    if output.termination_reason in {
        "timeout",
        "max_tool_calls_exceeded",
        "unrecoverable_failure",
    }:
        return False, satisfied, len(hard_constraints)

    if task.expected.kind == "clarification":
        success = (
            output.termination_reason == "clarification_needed"
            and not selected_listings
            and not output.selected_product_ids
            and not cart
            and task.expected.question_contains.casefold() in output.response_text.casefold()
        )
        return success, satisfied, len(hard_constraints)

    candidates = [
        (listing_id, product)
        for listing_id, product in views.items()
        if product.stock > 0 and all(matches(product, c) for c in hard_constraints)
    ]

    if task.expected.kind == "no_valid_product":
        success = (
            output.termination_reason == "no_valid_product"
            and not candidates
            and not selected_listings
            and not output.selected_product_ids
            and not cart
        )
        return success, satisfied, len(hard_constraints)

    if task.ranking_rule == "lowest_price" and candidates:
        best_price = min(product.price for _, product in candidates)
        winning_listings = {
            listing_id
            for listing_id, product in candidates
            if product.price == best_price
        }
    elif task.ranking_rule in {"highest_rating", "highest_rating_then_reviews"} and candidates:
        ranked = _rank_products([product for _, product in candidates], task.ranking_rule)
        ranked_keys = {(p.product_id, p.price, len(p.reviews)) for p in ranked}
        winning_listings = {
            listing_id
            for listing_id, product in candidates
            if (product.product_id, product.price, len(product.reviews)) in ranked_keys
            and average_rating(product) == average_rating(ranked[0])
        }
    else:
        winning_listings = {listing_id for listing_id, _ in candidates}

    if task.expected.valid_listing_ids:
        valid_ids = winning_listings & set(task.expected.valid_listing_ids)
    else:
        valid_product_ids = set(task.expected.valid_product_ids)
        valid_ids = {
            listing_id
            for listing_id in winning_listings
            if views[listing_id].product_id in valid_product_ids
        }
    selected = selected_listings
    success = (
        output.termination_reason == "completed"
        and len(selected) == 1
        and selected[0] in valid_ids
        and len(cart) == 1
        and cart[0].get("listing_id") == selected[0]
        and cart[0]["quantity"] == 1
        and cart[0]["in_stock"]
        and cart[0]["unit_price"] == views[selected[0]].price
        and snapshot["cart"]["total"] == views[selected[0]].price
    )
    return success, satisfied, len(hard_constraints)


def score(task: TaskDefinition, output: AgentOutput, snapshot: dict) -> tuple[bool, int, int]:
    # Multi-store snapshots always score via listings (incl. no_valid_product / clarification).
    if "listings" in snapshot:
        return _score_listings(task, output, snapshot)

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

    candidates = _rank_products(candidates, task.ranking_rule)
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
