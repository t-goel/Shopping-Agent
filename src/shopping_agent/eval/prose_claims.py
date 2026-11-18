"""Post-run extraction and audit of atomic product facts in free-text explanations.

Structured claims stay on the verifier. This module reads the explanation after
a trial and checks stated product facts against recorded get_listing (and
search) observations, preferring the latest observation of each product.
"""

from __future__ import annotations

import re
from collections import Counter

from pydantic import ValidationError

from shopping_agent.contracts import Product, TrialResult

_PRICE = re.compile(r"\$\s*(\d+(?:\.\d{1,2})?)")
_RATING = re.compile(
    r"(?:rated|rating|stars?|score)\s*(?:of|is|:)?\s*(\d(?:\.\d)?)"
    r"(?:\s*(?:out\s+of\s+5|/\s*5|stars?))?",
    re.IGNORECASE,
)
_STOCK_COUNT = re.compile(
    r"\b(\d+)\s+(?:units?|items?)\s+(?:left|remaining|in\s+stock|available)\b",
    re.IGNORECASE,
)
_IN_STOCK = re.compile(r"\b(?:in\s+stock|available)\b", re.IGNORECASE)
_OUT_OF_STOCK = re.compile(
    r"\b(?:out\s+of\s+stock|sold\s+out|unavailable)\b", re.IGNORECASE
)
_NEGATION = re.compile(
    r"\b(?:not|no|n't|never|without|isn't|isnt|aren't|arent|doesn't|doesnt)\b",
    re.IGNORECASE,
)
_WINDOW = 160


class ProseClaim:
    """One atomic product fact pulled from an explanation."""

    __slots__ = ("product_id", "field", "value", "text_span")

    def __init__(self, product_id: str, field: str, value, text_span: str = ""):
        self.product_id = product_id
        self.field = field
        self.value = value
        self.text_span = text_span

    def to_dict(self) -> dict:
        return {
            "product_id": self.product_id,
            "field": self.field,
            "value": self.value,
            "text_span": self.text_span,
        }


def _normalized(text: str) -> str:
    return " ".join(text.casefold().split())


def _products_from_snapshot(snapshot: dict | None) -> dict[str, Product]:
    products: dict[str, Product] = {}
    if not snapshot or not isinstance(snapshot.get("products"), dict):
        return products
    for pid, value in snapshot["products"].items():
        try:
            product = Product.model_validate(value)
        except (ValidationError, TypeError):
            continue
        if product.product_id == pid:
            products[pid] = product
    return products


def _record_product(obs: dict, observations: dict[str, dict]) -> None:
    product = obs.get("product", obs) if isinstance(obs, dict) else None
    if not isinstance(product, dict):
        return
    pid = product.get("product_id")
    if not isinstance(pid, str) or not pid:
        return
    row = observations.setdefault(pid, {})
    for field in ("price", "stock", "title", "category", "seller", "description"):
        if field in product:
            row[field] = product[field]
    if isinstance(product.get("attributes"), dict):
        row["attributes"] = product["attributes"]
    if isinstance(product.get("reviews"), list):
        row["reviews"] = product["reviews"]


def listing_observations(record: TrialResult) -> dict[str, dict]:
    """Latest recorded product facts, get_listing overwriting earlier search rows."""
    observations: dict[str, dict] = {}
    for event in record.tool_trace:
        if not isinstance(event, dict):
            continue
        name = event.get("name")
        obs = event.get("observation")
        if not isinstance(obs, dict):
            continue
        if name == "search":
            items = obs.get("items")
            if isinstance(items, list):
                for item in items:
                    if isinstance(item, dict):
                        _record_product(item, observations)
        elif name == "get_listing":
            _record_product(obs, observations)
    return observations


def _title_index(products: dict[str, Product]) -> list[tuple[str, re.Pattern]]:
    entries = []
    for pid, product in products.items():
        title = _normalized(product.title)
        if len(title) < 3:
            continue
        pattern = re.compile(r"(?<!\w)" + re.escape(title) + r"(?!\w)")
        entries.append((pid, title, pattern))
    entries.sort(key=lambda item: -len(item[1]))
    return [(pid, pattern) for pid, _title, pattern in entries]


def _mentions(text: str, products: dict[str, Product]) -> list[tuple[int, int, str]]:
    mentions: list[tuple[int, int, str]] = []
    for pid, pattern in _title_index(products):
        for match in pattern.finditer(text):
            if any(not (match.end() <= start or match.start() >= end) for start, end, _ in mentions):
                continue
            mentions.append((match.start(), match.end(), pid))
    return mentions


def _window(text: str, start: int, end: int) -> tuple[str, int]:
    left = max(0, start - _WINDOW)
    right = min(len(text), end + _WINDOW)
    return text[left:right], start - left


def _nearest(pos: int, mentions: list[tuple[int, int, str]]) -> str | None:
    best, best_dist = None, _WINDOW + 1
    for start, end, pid in mentions:
        dist = 0 if start <= pos <= end else min(abs(pos - start), abs(pos - end))
        if dist < best_dist:
            best, best_dist = pid, dist
    return best


def _negated(span: str, local_pos: int) -> bool:
    prefix = span[max(0, local_pos - 24):local_pos]
    return _NEGATION.search(prefix) is not None


def _span(text: str, start: int, end: int) -> str:
    return text[max(0, start - 12):end + 12].strip()


def _products_for_text(record: TrialResult) -> dict[str, Product]:
    products = _products_from_snapshot(record.final_state)
    # Titles the agent can name also come from listings it actually opened.
    for pid, row in listing_observations(record).items():
        if pid in products or not isinstance(row.get("title"), str):
            continue
        try:
            products[pid] = Product.model_validate({
                "product_id": pid,
                "title": row["title"],
                "description": row.get("description") or "",
                "category": row.get("category") or "unknown",
                "price": row.get("price") if isinstance(row.get("price"), (int, float)) else 0,
                "stock": row.get("stock") if isinstance(row.get("stock"), int) else 0,
                "seller": row.get("seller") or "unknown",
                "attributes": row.get("attributes") if isinstance(row.get("attributes"), dict) else {},
                "reviews": row.get("reviews") if isinstance(row.get("reviews"), list) else [],
            })
        except (ValidationError, TypeError):
            continue
    return products


def extract_prose_claims(response_text: str, products: dict[str, Product]) -> list[ProseClaim]:
    """Pull price, rating, stock, and asserted attribute facts tied to a title."""
    if not response_text or not products:
        return []
    text = _normalized(response_text)
    mentions = _mentions(text, products)
    if not mentions:
        return []

    claims: list[ProseClaim] = []
    seen: set[tuple] = set()

    def add(pid: str | None, field: str, value, start: int, end: int) -> None:
        if pid is None:
            return
        key = (pid, field, value)
        if key in seen:
            return
        seen.add(key)
        claims.append(ProseClaim(pid, field, value, _span(text, start, end)))

    for match in _PRICE.finditer(text):
        pid = _nearest(match.start(), mentions)
        if pid is None or _negated(_window(text, match.start(), match.end())[0], _window(text, match.start(), match.end())[1]):
            continue
        add(pid, "price", float(match.group(1)), match.start(), match.end())

    for match in _RATING.finditer(text):
        pid = _nearest(match.start(), mentions)
        if pid is None:
            continue
        add(pid, "rating", float(match.group(1)), match.start(), match.end())

    for match in _STOCK_COUNT.finditer(text):
        pid = _nearest(match.start(), mentions)
        if pid is None:
            continue
        add(pid, "stock", int(match.group(1)), match.start(), match.end())

    for match in _OUT_OF_STOCK.finditer(text):
        pid = _nearest(match.start(), mentions)
        if pid is None:
            continue
        add(pid, "stock_status", "out_of_stock", match.start(), match.end())

    for match in _IN_STOCK.finditer(text):
        pid = _nearest(match.start(), mentions)
        if pid is None or _negated(_window(text, match.start(), match.end())[0], _window(text, match.start(), match.end())[1]):
            continue
        add(pid, "stock_status", "in_stock", match.start(), match.end())

    for start, end, pid in mentions:
        product = products[pid]
        window, title_at = _window(text, start, end)
        for name, value in product.attributes.items():
            if not isinstance(value, (str, int, float)) or isinstance(value, bool):
                continue
            token = _normalized(str(value))
            if len(token) < 1:
                continue
            pattern = re.compile(r"(?<!\w)" + re.escape(token) + r"(?!\w)")
            for match in pattern.finditer(window):
                if _negated(window, match.start()):
                    continue
                # The title itself does not count as asserting the attribute.
                if match.start() < title_at + (end - start) and match.end() > title_at:
                    continue
                abs_start = (start - _WINDOW if start >= _WINDOW else 0) + match.start()
                add(pid, name, value, abs_start, abs_start + (match.end() - match.start()))
        for name, value in product.attributes.items():
            if not isinstance(value, bool):
                continue
            label = name.replace("_", " ")
            pattern = re.compile(r"(?<!\w)" + re.escape(label) + r"(?!\w)")
            for match in pattern.finditer(window):
                claimed = not _negated(window, match.start())
                if match.start() < title_at + (end - start) and match.end() > title_at:
                    continue
                add(
                    pid,
                    name,
                    claimed,
                    start - (_WINDOW if start >= _WINDOW else start) + match.start(),
                    start - (_WINDOW if start >= _WINDOW else start) + match.end(),
                )
    return claims


def _average_rating(reviews) -> float | None:
    ratings = []
    for review in reviews or []:
        rating = review.get("rating") if isinstance(review, dict) else getattr(review, "rating", None)
        if isinstance(rating, (int, float)):
            ratings.append(rating)
    if not ratings:
        return None
    return sum(ratings) / len(ratings)


def _observed(claim: ProseClaim, product: Product | None, observed: dict) -> tuple[object, str | None]:
    source = "final_state" if product is not None else ("get_listing" if observed else None)
    row = product

    def field(name: str):
        if product is not None:
            return getattr(product, name)
        return observed.get(name)

    if claim.field == "price":
        return field("price"), source if field("price") is not None else None
    if claim.field == "stock":
        return field("stock"), source if field("stock") is not None else None
    if claim.field == "stock_status":
        stock = field("stock")
        if stock is None:
            return None, None
        return ("in_stock" if stock > 0 else "out_of_stock"), source
    if claim.field == "rating":
        reviews = product.reviews if product is not None else observed.get("reviews")
        avg = _average_rating(reviews)
        if avg is None:
            return None, None
        return round(avg, 2), source
    if product is not None and claim.field in type(product).model_fields:
        return getattr(product, claim.field), "final_state"
    if product is not None and claim.field in product.attributes:
        return product.attributes[claim.field], "final_state"
    attrs = observed.get("attributes") if isinstance(observed.get("attributes"), dict) else {}
    if claim.field in attrs:
        return attrs[claim.field], "get_listing"
    if claim.field in observed:
        return observed[claim.field], "get_listing"
    return None, None


def _matches(claimed, observed) -> bool:
    if isinstance(claimed, float) or isinstance(observed, float):
        try:
            return abs(float(claimed) - float(observed)) < 0.051
        except (TypeError, ValueError):
            return False
    return claimed == observed


def audit_prose_claim(
    claim: ProseClaim,
    observations: dict[str, dict],
    final_products: dict[str, Product],
) -> dict:
    """Compare one extracted fact with the latest recorded listing, else final state."""
    result = {**claim.to_dict(), "status": "unknown", "observed_value": None, "source": None}
    observed = observations.get(claim.product_id, {})
    product = final_products.get(claim.product_id)
    # get_listing observations are the evidence the explanation may use.
    # Final state is the fallback when the trial recorded no listing observation.
    primary = observed if observed else {}
    value, source = _observed(claim, product if not observed else None, primary)
    if source is None:
        return result
    result["observed_value"] = value
    result["source"] = source
    result["status"] = "supports" if _matches(claim.value, value) else "contradicts"
    return result


def audit_prose_claims(record: TrialResult) -> dict:
    """Extract explanation facts and score them against recorded observations."""
    final_products = _products_from_snapshot(record.final_state)
    observations = listing_observations(record)
    products = _products_for_text(record)
    extracted = extract_prose_claims(record.response_text, products)
    audited = [audit_prose_claim(claim, observations, final_products) for claim in extracted]
    counts = Counter(item["status"] for item in audited)
    assessed = counts["supports"] + counts["contradicts"]
    return {
        "task_id": record.task_id,
        "trial_number": record.trial_number,
        "prose_claims": audited,
        "prose_claim_counts": {
            "supports": counts.get("supports", 0),
            "contradicts": counts.get("contradicts", 0),
            "unknown": counts.get("unknown", 0),
        },
        "assessable_prose_claims": assessed,
        "unsupported_claim_rate": counts["contradicts"] / assessed if assessed else None,
    }


def aggregate_prose_audits(trial_audits: list[dict]) -> dict:
    supports = sum(item["prose_claim_counts"]["supports"] for item in trial_audits)
    contradicts = sum(item["prose_claim_counts"]["contradicts"] for item in trial_audits)
    unknown = sum(item["prose_claim_counts"]["unknown"] for item in trial_audits)
    assessed = supports + contradicts
    return {
        "prose_claims": {"supports": supports, "contradicts": contradicts, "unknown": unknown},
        "assessable_prose_claims": assessed,
        "unsupported_claim_rate": contradicts / assessed if assessed else None,
        "trials_with_prose_claims": sum(bool(item["prose_claims"]) for item in trial_audits),
    }


def unsupported_claim_rate(records: list[TrialResult]) -> float | None:
    """Share of assessable prose facts that contradict recorded observations."""
    return aggregate_prose_audits([audit_prose_claims(record) for record in records])[
        "unsupported_claim_rate"
    ]
