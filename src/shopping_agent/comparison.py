"""Typed field comparisons shared by verification and benchmark authoring."""

import re

from shopping_agent.contracts import Constraint, Operator, Product


_SIZE_ALIASES = {
    "xs": "XS", "s": "S", "m": "M", "l": "L", "xl": "XL",
    "extra small": "XS", "extra-small": "XS", "small": "S",
    "medium": "M", "large": "L", "extra large": "XL", "extra-large": "XL",
}


def canonical_size(value) -> str | None:
    """Reduce provider and catalog size spellings to one comparable token.

    A provider may answer ``"medium"``, ``9`` or ``"US 9 men's"`` where the
    catalog stores ``"M"`` or ``"9"``. Canonicalizing both sides here (rather
    than rewriting a single constraint value from one observation) keeps
    verification and scoring consistent across multi-store catalogs whose
    listings spell equivalent sizes differently.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return str(int(number)) if number.is_integer() else str(number)
    if isinstance(value, str):
        text = value.strip()
        number = re.search(r"\d+(?:\.\d+)?", text)
        if number:
            parsed = float(number.group(0))
            return str(int(parsed)) if parsed.is_integer() else number.group(0)
        key = text.casefold()
        if key in _SIZE_ALIASES:
            return _SIZE_ALIASES[key]
        if text.upper() in {"XS", "S", "M", "L", "XL"}:
            return text.upper()
    return None


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

    if constraint.attribute == "size" and constraint.operator == Operator.EQ:
        observed_size = canonical_size(value)
        target_size = canonical_size(target)
        if observed_size is not None and target_size is not None:
            return observed_size == target_size

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


