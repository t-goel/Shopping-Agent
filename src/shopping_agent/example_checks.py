"""Authoring checks for benchmark examples; these are never exposed to the agent."""

from shopping_agent.contracts import CatalogExample, Constraint, Operator, Product, TaskDefinition


# Compare typed listing values without treating missing fields or booleans as numeric matches.
def matches(product: Product, constraint: Constraint) -> bool:
    value = getattr(
        product,
        constraint.attribute,
        product.attributes.get(constraint.attribute),
    )
    target = constraint.value

    if value is None:
        return False

    numeric = type(value) in (int, float) and type(target) in (int, float)

    if not numeric and type(value) is not type(target):
        return False

    if constraint.operator == Operator.EQ:
        return value == target

    if constraint.operator == Operator.CONTAINS:
        return (
            isinstance(value, str)
            and isinstance(target, str)
            and target.casefold() in value.casefold()
        )

    if not numeric:
        return False

    if constraint.operator == Operator.GTE:
        return value >= target

    if constraint.operator == Operator.LTE:
        return value <= target

    return False


# Compute valid winners after scheduled changes, keeping ties as equally valid answers.
def expected_products(catalog: CatalogExample, task: TaskDefinition) -> set[str]:
    products = {
        product.product_id: product.model_copy(deep=True)
        for product in catalog.products
    }

    for mutation in task.mutations:
        product = products[mutation.product_id]

        if mutation.price is not None:
            product.price = mutation.price

        if mutation.stock is not None:
            product.stock = mutation.stock

    candidates = [
        product for product in products.values()
        if product.stock > 0 and all(matches(product, c) for c in task.request.constraints if c.hard)
    ]

    if not candidates:
        return set()

    if task.ranking_rule == "lowest_price":
        best = min(product.price for product in candidates)
        candidates = [product for product in candidates if product.price == best]

    elif task.ranking_rule == "highest_rating":
        def rating(product: Product) -> float:
            if not product.reviews:
                return -1

            return sum(r.rating for r in product.reviews) / len(product.reviews)

        best = max(rating(product) for product in candidates)
        candidates = [product for product in candidates if rating(product) == best]

    return {product.product_id for product in candidates}
