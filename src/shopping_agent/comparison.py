"""Typed field comparisons shared by verification and benchmark authoring."""

from shopping_agent.contracts import Constraint, Operator, Product


# Compare typed listing values without treating missing fields or booleans as numeric matches.
def matches(product: Product, constraint: Constraint, tolerance: float | None = None) -> bool:
    prod = getattr(product, "product", product)
    attrs = getattr(prod, "attributes", {}) or {}
    if constraint.attribute in type(prod).model_fields:
        value = getattr(prod, constraint.attribute)
    elif isinstance(attrs, dict):
        value = attrs.get(constraint.attribute)
    else:
        value = None
    target = constraint.value

    if value is None:
        return False

    numeric = type(value) in (int, float) and type(target) in (int, float)

    if not numeric and type(value) is not type(target):
        return False

    eff_tolerance = tolerance if tolerance is not None else getattr(constraint, "tolerance", None)

    if constraint.operator == Operator.EQ:
        if numeric and eff_tolerance is not None:
            return abs(value - target) <= eff_tolerance
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
        if eff_tolerance is not None:
            return value >= target - eff_tolerance
        return value >= target

    if constraint.operator == Operator.LTE:
        if eff_tolerance is not None:
            return value <= target + eff_tolerance
        return value <= target

    return False


def capacity_matches(actual: float, target: float, tolerance: float = 5.0) -> bool:
    """Check if actual capacity matches target within realistic bounds / tolerance."""
    return abs(actual - target) <= tolerance


def approximate_bounds(value: float, tolerance: float = 5.0) -> tuple[float, float]:
    """Compute realistic lower and upper bounds for an approximate quantity."""
    return (value - tolerance, value + tolerance)


