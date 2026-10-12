"""Typed field comparisons shared by verification and benchmark authoring."""

from shopping_agent.contracts import Constraint, Operator, Product


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


