"""Typed field comparisons shared by verification and benchmark authoring."""

import re
from typing import Any

from shopping_agent.contracts import Constraint, Operator, Product

_CANONICAL_SIZES = {
    "xs": "XS",
    "extra small": "XS",
    "extra-small": "XS",
    "extrasmall": "XS",
    "s": "S",
    "small": "S",
    "m": "M",
    "medium": "M",
    "med": "M",
    "l": "L",
    "large": "L",
    "xl": "XL",
    "extra large": "XL",
    "extra-large": "XL",
    "extralarge": "XL",
    "xxl": "XXL",
    "2xl": "XXL",
    "xx-large": "XXL",
    "xxlarge": "XXL",
}


def canonicalize_size(val: Any) -> Any:
    """Canonicalize apparel and footwear sizes for alias and numeric-string equivalence."""
    if val is None:
        return None
    if isinstance(val, (int, float)) and not isinstance(val, bool):
        f = float(val)
        return str(int(f)) if f.is_integer() else str(f)
    s = str(val).strip()
    s_cf = s.casefold()
    if s_cf in _CANONICAL_SIZES:
        return _CANONICAL_SIZES[s_cf]

    # Check for numeric / US shoe sizing (e.g. "US 9 men's", "Men's US 9", "size 9", "9.5")
    num_only_match = re.search(r"\b(\d+(?:\.\d+)?)\b", s_cf)
    if num_only_match:
        cleaned = re.sub(
            r"\b(?:us|men'?s|mens|women'?s|womens|size|shoe|shoes|m|w)\b", "", s_cf
        ).strip(": -")
        cleaned = cleaned.strip()
        try:
            num = float(cleaned)
            return str(int(num)) if num.is_integer() else str(num)
        except ValueError:
            pass

    # Check for embedded letter/word sizes
    words = re.findall(r"\b[a-zA-Z0-9.-]+\b", s_cf)
    for w in words:
        if w in _CANONICAL_SIZES:
            return _CANONICAL_SIZES[w]

    return s


def coerce_numeric(v: Any) -> float | None:
    """Extract float from numeric values or strings with units/symbols (e.g. '$70', '30L')."""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        cleaned = v.strip()
        cleaned = re.sub(r"^[~$€£\s]+", "", cleaned)
        cleaned = re.sub(r"^(?:approx(?:imately)?|around|about)\s*", "", cleaned, flags=re.I)
        cleaned = re.sub(
            r"\s*(?:usd|dollars?|bucks?|liters?|litres?|l)\b.*$", "", cleaned, flags=re.I
        )
        cleaned = cleaned.strip()
        try:
            return float(cleaned)
        except ValueError:
            return None
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

    eff_tolerance = tolerance if tolerance is not None else getattr(constraint, "tolerance", None)

    # Size attribute handling: canonicalize sizes so strict matches treat equivalent forms as equal
    if constraint.attribute == "size":
        c_val = canonicalize_size(value)
        c_target = canonicalize_size(target)
        if constraint.operator == Operator.EQ:
            return c_val == c_target
        if constraint.operator == Operator.CONTAINS:
            return (
                isinstance(c_val, str)
                and isinstance(c_target, str)
                and c_target.casefold() in c_val.casefold()
            )

    # Coerce numeric strings/units for numeric comparisons
    v_num = coerce_numeric(value)
    t_num = coerce_numeric(target)
    numeric = v_num is not None and t_num is not None
    if numeric:
        value = v_num
        target = t_num

    # Coerce boolean strings for comparison
    if isinstance(value, bool) and isinstance(target, str) and target.casefold() in {"true", "false"}:
        target = (target.casefold() == "true")
    elif isinstance(target, bool) and isinstance(value, str) and value.casefold() in {"true", "false"}:
        value = (value.casefold() == "true")

    if not numeric and type(value) is not type(target):
        return False

    # Capacity tolerance: apply default 5.0L tolerance for approximate capacity if not explicitly given
    if constraint.attribute == "capacity_liters" and numeric and eff_tolerance is None:
        if isinstance(constraint.value, str) and ("~" in constraint.value or "approx" in constraint.value.casefold()):
            eff_tolerance = 5.0

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


