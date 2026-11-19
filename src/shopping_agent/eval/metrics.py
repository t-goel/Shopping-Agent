"""One vocabulary for failure categories and claim metrics.

Every reporting surface (terminal summary, JSON summary, markdown report,
condition comparison, and the read-only audit) classifies failures and scores
declared claims through this module, so the same outcome never appears under two
names and no surface re-derives a claim verdict on its own.

Failure categories describe observable outcomes only. Root causes require trace
inspection and are never inferred here.
"""

from __future__ import annotations

from collections import Counter
from enum import StrEnum

from pydantic import ValidationError

from shopping_agent.comparison import matches
from shopping_agent.contracts import Constraint, Product, TrialResult
from shopping_agent.interfaces import Claim

# Termination reasons that end a trial before any scored outcome.
TERMINAL_FAILURE_REASONS = frozenset({
    "timeout",
    "max_tool_calls_exceeded",
    "unrecoverable_failure",
})

CLAIM_STATUSES = ("supports", "contradicts", "unknown", "invalid")


class FailureCategory(StrEnum):
    """Canonical failure names shared by the terminal and machine-readable reports."""

    UNRECOVERABLE_FAILURE = "unrecoverable_failure"
    TIMEOUT = "timeout"
    MAX_TOOL_CALLS_EXCEEDED = "max_tool_calls_exceeded"
    CLARIFICATION_MISMATCH = "clarification_mismatch"
    UNEXPECTED_CLARIFICATION = "unexpected_clarification"
    INCORRECT_ABSTENTION = "incorrect_abstention"
    ABSTENTION_MISMATCH = "abstention_mismatch"
    HARD_CONSTRAINT_VIOLATION = "hard_constraint_violation"
    SELECTION_OR_CART_MISMATCH = "selection_or_cart_mismatch"


FAILURE_CATEGORY_DESCRIPTIONS = {
    FailureCategory.UNRECOVERABLE_FAILURE: "the trial raised or died before a scored outcome",
    FailureCategory.TIMEOUT: "the trial exceeded its wall-clock budget",
    FailureCategory.MAX_TOOL_CALLS_EXCEEDED: "the trial exceeded its tool-call budget",
    FailureCategory.CLARIFICATION_MISMATCH: "the required clarification question was not asked",
    FailureCategory.UNEXPECTED_CLARIFICATION: "the agent asked a question on a product task",
    FailureCategory.INCORRECT_ABSTENTION: "the agent abstained where a product choice was required",
    FailureCategory.ABSTENTION_MISMATCH: "abstention and selection were swapped relative to the task",
    FailureCategory.HARD_CONSTRAINT_VIOLATION: "the recorded selection violates a hard constraint",
    FailureCategory.SELECTION_OR_CART_MISMATCH: "the reported outcome, selection, or cart did not match",
}


def _terminal_category(reason: str) -> FailureCategory:
    if reason == "timeout":
        return FailureCategory.TIMEOUT
    if reason == "max_tool_calls_exceeded":
        return FailureCategory.MAX_TOOL_CALLS_EXCEEDED
    return FailureCategory.UNRECOVERABLE_FAILURE


def failure_category(record: TrialResult) -> FailureCategory | None:
    """Classify one unsuccessful trial; successful trials have no category."""
    if record.is_successful:
        return None
    if record.error or record.termination_reason in TERMINAL_FAILURE_REASONS:
        return _terminal_category(record.termination_reason)
    if record.expected_kind == "clarification":
        return FailureCategory.CLARIFICATION_MISMATCH
    if record.termination_reason == "clarification_needed":
        # Product-task clarifications are unexpected asks, not constraint failures.
        return FailureCategory.UNEXPECTED_CLARIFICATION
    if record.termination_reason == "no_valid_product":
        # Only a false abstention when a product selection was required.
        if record.expected_kind == "product":
            return FailureCategory.INCORRECT_ABSTENTION
        return FailureCategory.ABSTENTION_MISMATCH
    if record.expected_kind == "product" and record.constraints_satisfied < record.total_constraints:
        return FailureCategory.HARD_CONSTRAINT_VIOLATION
    return FailureCategory.SELECTION_OR_CART_MISMATCH


def failure_category_legend() -> dict[str, str]:
    """Category name to one-line description, in canonical order."""
    return {category.value: FAILURE_CATEGORY_DESCRIPTIONS[category] for category in FailureCategory}


def final_products(record: TrialResult) -> dict[str, Product]:
    """Authoritative products from the trial's final catalog snapshot."""
    products: dict[str, Product] = {}
    snapshot = record.final_state
    if not isinstance(snapshot, dict):
        return products
    rows = snapshot.get("products")
    if not isinstance(rows, dict):
        return products
    for product_id, value in rows.items():
        try:
            product = Product.model_validate(value)
        except (ValidationError, TypeError):
            # Missing or malformed facts cannot support a claim.
            continue
        if product.product_id == product_id:
            products[product_id] = product
    return products


def claim_audit(record: TrialResult, products: dict[str, Product] | None = None) -> list[dict]:
    """Status of every recorded structured claim against the final catalog state."""
    products = final_products(record) if products is None else products
    audited = []
    for index, raw in enumerate(record.claims):
        entry = {"index": index, "status": "invalid", "observed_value": None}
        try:
            claim = Claim.model_validate(raw)
        except (ValidationError, TypeError):
            audited.append(entry)
            continue
        entry.update(
            claim_id=claim.claim_id,
            product_id=claim.product_id,
            field=claim.field,
            claimed_value=claim.value,
            status="unknown",
        )
        product = products.get(claim.product_id)
        if product is not None:
            value = (
                getattr(product, claim.field)
                if claim.field in type(product).model_fields
                else product.attributes.get(claim.field)
            )
            if type(value) in (str, int, float, bool):
                entry["observed_value"] = value
                entry["status"] = "supports" if matches(product, Constraint(
                    attribute=claim.field, operator="eq", value=claim.value)) else "contradicts"
        audited.append(entry)
    return audited


def structured_claim_summary(records: list[TrialResult]) -> dict:
    """Aggregate recorded claims; the rate stays null when nothing is checkable."""
    audits = [claim_audit(record) for record in records]
    counts = Counter(row["status"] for audit in audits for row in audit)
    assessed = counts["supports"] + counts["contradicts"]
    return {
        "structured_claims": {status: counts.get(status, 0) for status in CLAIM_STATUSES},
        "assessable_claims": assessed,
        "unsupported_claim_rate": counts["contradicts"] / assessed if assessed else None,
        "trials_with_claims": sum(bool(audit) for audit in audits),
    }


def tool_calls_by_purpose(records: list[TrialResult]) -> dict[str, int]:
    """Split recorded tool calls into agent exploration and gate verification."""
    counts = Counter()
    for record in records:
        for event in record.tool_trace:
            if not isinstance(event, dict):
                continue
            counts[event.get("purpose") or "unspecified"] += 1
    return dict(counts)