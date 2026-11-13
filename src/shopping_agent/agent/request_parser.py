"""Convert common natural-language shopping requests into typed constraints."""

import re
from typing import Literal

from shopping_agent.contracts import Constraint, ShoppingRequest

RankingRule = Literal["lowest_price", "highest_rating", "none"]

_CATEGORY_ALIASES = {
    "jacket": "jackets",
    "jackets": "jackets",
    "coat": "jackets",
    "coats": "jackets",
    "rain shell": "jackets",
    "shell": "jackets",
    "bag": "bags",
    "bags": "bags",
    "backpack": "bags",
    "backpacks": "bags",
}
_SIZE_ALIASES = {
    "extra small": "XS",
    "extra-small": "XS",
    "small": "S",
    "medium": "M",
    "large": "L",
    "extra large": "XL",
    "extra-large": "XL",
    "xs": "XS",
    "s": "S",
    "m": "M",
    "l": "L",
    "xl": "XL",
}


def _add_constraint(constraints: list[Constraint], constraint: Constraint) -> None:
    if not any(
        existing.attribute == constraint.attribute
        and existing.operator == constraint.operator
        and existing.value == constraint.value
        for existing in constraints
    ):
        constraints.append(constraint)


def parse_request(query: str) -> tuple[ShoppingRequest, RankingRule]:
    """Parse supported request language without pretending to solve ambiguity.

    The parser is intentionally conservative: it extracts only constraints
    supported by the product contract and asks for clarification when it cannot
    identify a product category.
    """

    if not query or not query.strip():
        raise ValueError("shopping query must not be empty")

    text = " ".join(query.casefold().split())
    constraints: list[Constraint] = []

    category = next(
        (value for alias, value in _CATEGORY_ALIASES.items()
         if re.search(rf"\b{re.escape(alias)}\b", text)),
        None,
    )
    if category:
        _add_constraint(constraints, Constraint(
            attribute="category", operator="eq", value=category,
        ))

    negative_waterproof = re.search(
        r"\b(?:not\s+|non[- ]?|without\s+)(?:waterproof|water-proof)\b", text,
    )
    if negative_waterproof:
        _add_constraint(constraints, Constraint(
            attribute="waterproof", operator="eq", value=False,
        ))
    elif re.search(r"\bwater[- ]?proof\b", text):
        _add_constraint(constraints, Constraint(
            attribute="waterproof", operator="eq", value=True,
        ))

    size_match = re.search(
        r"\b(?:size\s*(?P<symbol>xs|xl|s|m|l)\b"
        r"|size\s+(?P<word>extra[- ]?small|extra[- ]?large|small|medium|large)\b"
        r"|(?P<standalone>extra[- ]?small|extra[- ]?large|small|medium|large)\s+size\b)",
        text,
    )
    if size_match:
        size = size_match.group("symbol") or size_match.group("word") or size_match.group("standalone")
        _add_constraint(constraints, Constraint(
            attribute="size", operator="eq", value=_SIZE_ALIASES[size],
        ))

    price_match = re.search(
        r"\b(?:under|below|less than|at most|up to|no more than)\s*\$?\s*"
        r"(?P<amount>\d+(?:\.\d{1,2})?)\b",
        text,
    )
    if price_match:
        _add_constraint(constraints, Constraint(
            attribute="price", operator="lte", value=float(price_match.group("amount")),
        ))
    else:
        price_match = re.search(
            r"\b(?:over|above|more than|at least|no less than)\s*\$?\s*"
            r"(?P<amount>\d+(?:\.\d{1,2})?)\b",
            text,
        )
        if price_match:
            _add_constraint(constraints, Constraint(
                attribute="price", operator="gte", value=float(price_match.group("amount")),
            ))

    if re.search(r"\b(?:cheapest|least expensive|most affordable|lowest price)\b", text):
        ranking: RankingRule = "lowest_price"
    elif re.search(r"\b(?:highest rated|best rated|top rated|best reviewed)\b", text):
        ranking = "highest_rating"
    else:
        ranking = "none"

    clarification = None
    if not category:
        clarification = "What type of product should I look for?"

    return ShoppingRequest(
        original_text=query,
        constraints=constraints,
        clarification_needed=clarification,
    ), ranking
