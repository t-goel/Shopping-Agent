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

_ORDERED_SIZE_KEYS = sorted(_CANONICAL_SIZES.keys(), key=len, reverse=True)


def canonicalize_size(val: Any) -> Any:
    """Canonicalize apparel and footwear sizes for alias and numeric-string equivalence."""
    if val is None:
        return None
    if isinstance(val, (int, float)) and not isinstance(val, bool):
        f = float(val)
        return str(int(f)) if f.is_integer() else str(f)
    s = str(val).strip()
    if not s:
        return s
    s_cf = s.casefold()
    if s_cf in _CANONICAL_SIZES:
        return _CANONICAL_SIZES[s_cf]

    # Strip possessive 's to prevent possessive nouns from matching size "S"
    cleaned_cf = re.sub(r"['’]s\b", "", s_cf)
    cleaned_cf = re.sub(
        r"\b(?:us|uk|eu|men|mens|women|womens|unisex|kids?|boys?|girls?|size|shoe|shoes)\b", " ", cleaned_cf
    )
    cleaned_cf = re.sub(r"[:\-_/]+", " ", cleaned_cf).strip()

    if cleaned_cf in _CANONICAL_SIZES:
        return _CANONICAL_SIZES[cleaned_cf]

    # If cleaned text is purely numeric, return canonical numeric string
    try:
        num = float(cleaned_cf)
        return str(int(num)) if num.is_integer() else str(num)
    except ValueError:
        pass

    # Check for numeric pattern if embedded with shoe sizing qualifiers
    num_match = re.search(r"\b(\d+(?:\.\d+)?)\b", cleaned_cf)
    if num_match:
        num_str = num_match.group(1)
        rem = re.sub(r"\b" + re.escape(num_str) + r"\b", "", cleaned_cf).strip()
        if not rem or rem in {"m", "w", "d", "ee"}:
            num = float(num_str)
            return str(int(num)) if num.is_integer() else str(num)

    # Check for embedded letter/word sizes, checking longer phrases first
    for k in _ORDERED_SIZE_KEYS:
        if re.search(r"\b" + re.escape(k) + r"\b", cleaned_cf):
            return _CANONICAL_SIZES[k]

    return s


def coerce_numeric(v: Any) -> float | None:
    """Extract float from numeric values or strings with units/symbols (e.g. '$70', '30L')."""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        cleaned = v.strip()
        cleaned = re.sub(r"^(?:approx(?:imately)?\.?|around|about)\s*", "", cleaned, flags=re.I)
        cleaned = re.sub(r"^[~$€£\s]+", "", cleaned)
        cleaned = re.sub(
            r"\s*(?:usd|dollars?|bucks?|liters?|litres?|l)\b.*$", "", cleaned, flags=re.I
        )
        cleaned = cleaned.strip()
        try:
            return float(cleaned)
        except ValueError:
            return None
    return None


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
        value = c_val
        target = c_target

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


