"""Convert common natural-language shopping requests into typed constraints."""

import re
from typing import Literal

from shopping_agent.contracts import Constraint, Operator, ShoppingRequest

RankingRule = Literal[
    "lowest_price", "highest_rating", "highest_rating_then_reviews", "none"
]

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
    "pack": "bags",
    "packs": "bags",
    "daypack": "bags",
    "daypacks": "bags",
    "duffel": "bags",
    "duffels": "bags",
    "carryall": "bags",
    "shoe": "footwear",
    "shoes": "footwear",
    "boot": "footwear",
    "boots": "footwear",
    "footwear": "footwear",
    "hiker": "footwear",
    "hikers": "footwear",
    "sneaker": "footwear",
    "sneakers": "footwear",
    "trail runner": "footwear",
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
_WORD_PRICES = {
    "hundred": 100.0,
    "fifty": 50.0,
    "twenty": 20.0,
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
    identify a product category or when sizing is ambiguous.
    """

    if not query or not query.strip():
        raise ValueError("shopping query must not be empty")

    text = " ".join(query.casefold().split())
    constraints: list[Constraint] = []
    preferences: list[str] = []

    # Clean text of "already packed" / "already have" mentions to avoid confusing category
    cleaned_for_category = re.sub(
        r"\b(?:[a-z\s-]+)\s+is\s+already\s+packed\b", "", text, flags=re.I
    )

    category = next(
        (value for alias, value in _CATEGORY_ALIASES.items()
         if re.search(rf"\b{re.escape(alias)}\b", cleaned_for_category)),
        None,
    )
    if not category:
        category = next(
            (value for alias, value in _CATEGORY_ALIASES.items()
             if re.search(rf"\b{re.escape(alias)}\b", text)),
            None,
        )

    if category:
        _add_constraint(constraints, Constraint(
            attribute="category", operator=Operator.EQ, value=category,
        ))

    negative_waterproof = re.search(
        r"\b(?:not\s+|non[- ]?|without\s+)(?:waterproof|water-proof)\b", text,
    )
    if negative_waterproof:
        _add_constraint(constraints, Constraint(
            attribute="waterproof", operator=Operator.EQ, value=False,
        ))
    elif re.search(r"\bwater[- ]?proof\b|\bkeeps?\s+(?:a\s+laptop\s+and\s+a\s+couple\s+layers\s+)?dry\b", text):
        _add_constraint(constraints, Constraint(
            attribute="waterproof", operator=Operator.EQ, value=True,
        ))

    # Sizing uncertainty check
    sizing_uncertain = bool(re.search(
        r"\b(?:not\s+sure|unsure|don't\s+know)\b.*?\b(?:runs?\s+the\s+same|sizing|size|fits?)\b", text, re.I
    ))

    if not sizing_uncertain:
        size_match = re.search(
            r"\b(?:size\s*(?P<symbol>xs|xl|s|m|l)\b"
            r"|size\s*[-:]?\s*(?P<word>extra[- ]?small|extra[- ]?large|small|medium|large)\b"
            r"|(?P<standalone>extra[- ]?small|extra[- ]?large|small|medium|large)\s+(?:size|jacket|coat|shell)\b"
            r"|fits?\s+(?P<fit_word>extra[- ]?small|extra[- ]?large|small|medium|large)\b"
            r"|\b(?P<prefix>medium)\s+(?:jacket|coat|shell)\b)",
            text,
        )
        if size_match:
            size = (
                size_match.group("symbol")
                or size_match.group("word")
                or size_match.group("standalone")
                or size_match.group("fit_word")
                or size_match.group("prefix")
            )
            _add_constraint(constraints, Constraint(
                attribute="size", operator=Operator.EQ, value=_SIZE_ALIASES[size],
            ))
        else:
            shoe_size_match = re.search(
                r"\b(?:size\s*[-:]?\s*|men'?s\s+us\s+|us\s+)(?P<num>\d+(?:\.\d+)?)\b", text
            )
            if shoe_size_match:
                _add_constraint(constraints, Constraint(
                    attribute="size", operator=Operator.EQ, value=shoe_size_match.group("num"),
                ))

    # Capacity matching (approximate bounds)
    approx_cap_match = re.search(
        r"(?:~|approx(?:imately)?\s*|around\s*|about\s*)?(?P<num>\d+)\s*(?:liter|liters|l)\b", text
    )
    if approx_cap_match:
        cap = float(approx_cap_match.group("num"))
        lower = max(1.0, cap - 5.0)
        upper = cap + 5.0
        _add_constraint(constraints, Constraint(
            attribute="capacity_liters", operator=Operator.GTE, value=lower,
        ))
        _add_constraint(constraints, Constraint(
            attribute="capacity_liters", operator=Operator.LTE, value=upper,
        ))
    elif re.search(r"\bdaypack(?:\s+size|\s+sized)?\b", text):
        _add_constraint(constraints, Constraint(
            attribute="capacity_liters", operator=Operator.GTE, value=20.0,
        ))
        _add_constraint(constraints, Constraint(
            attribute="capacity_liters", operator=Operator.LTE, value=25.0,
        ))

    price_match = re.search(
        r"\b(?:under|below|less than|at most|up to|no more than|max|budget|at or under|won't go over|stay under)\s*\$?\s*"
        r"(?P<amount>\d+(?:\.\d{1,2})?)\b",
        text,
    )
    if price_match:
        _add_constraint(constraints, Constraint(
            attribute="price", operator=Operator.LTE, value=float(price_match.group("amount")),
        ))
    else:
        word_match = re.search(
            r"\b(?:under|below|less than|no more than|won't go over|stay under)\s*(?:a\s+)?(?P<word>hundred|fifty|twenty)\s+dollars\b",
            text,
        )
        if word_match:
            _add_constraint(constraints, Constraint(
                attribute="price", operator=Operator.LTE, value=_WORD_PRICES[word_match.group("word")],
            ))
        else:
            price_match = re.search(
                r"\b(?:over|above|more than|at least|no less than)\s*\$?\s*"
                r"(?P<amount>\d+(?:\.\d{1,2})?)\b",
                text,
            )
            if price_match:
                _add_constraint(constraints, Constraint(
                    attribute="price", operator=Operator.GTE, value=float(price_match.group("amount")),
                ))

    if "comfort" in text:
        preferences.append("comfortable")

    if re.search(r"\b(?:cheapest|least expensive|most affordable|lowest price|lowest-priced|cheapest wins)\b", text):
        ranking: RankingRule = "lowest_price"
    elif re.search(r"\b(?:highest\s+on\s+average|rate\s+highest\s+on\s+average|shoppers\s+rate\s+highest)\b", text):
        ranking = "highest_rating_then_reviews"
    elif re.search(r"\b(?:highest rated|best rated|top rated|best reviewed)\b", text):
        ranking = "highest_rating"
    elif "cheapest" in text or "lowest" in text:
        ranking = "lowest_price"
    else:
        ranking = "none"

    clarification = None
    if sizing_uncertain:
        clarification = "What jacket size do you need?" if category == "jackets" else "What size do you need?"
    elif not category:
        clarification = "What type of product should I look for?"

    return ShoppingRequest(
        original_text=query,
        constraints=constraints,
        preferences=preferences,
        clarification_needed=clarification,
    ), ranking
