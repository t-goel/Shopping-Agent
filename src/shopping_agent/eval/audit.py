"""Read-only audits of saved trials against final state, not agent evidence."""

import hashlib
import json
import re
from collections import Counter
from pathlib import Path

from shopping_agent.contracts import TrialResult
from shopping_agent.eval.metrics import claim_audit, final_products, structured_claim_summary
from shopping_agent.eval.prose_claims import aggregate_prose_audits, audit_prose_claims


def normalized(text):
    return " ".join(text.casefold().split())


def cart_quantities(items):
    """Accumulate cart quantity per product_id (not row count)."""
    quantities = Counter()
    for row in items:
        quantities[row["product_id"] if isinstance(row, dict) else row.product_id] += (
            row["quantity"] if isinstance(row, dict) else row.quantity
        )
    return quantities


def audit_trial(record: TrialResult):
    result = {
        "task_id": record.task_id, "trial_number": record.trial_number,
        "agent_name": record.agent_name, "model_id": record.model_id,
        "original_success": record.is_successful,
        "selection_cart_consistency": "unassessable",
        "recorded_cart_consistency": "unassessable",
        "claims": [], "response_title_review": [],
    }
    snapshot = record.final_state
    products = final_products(record)

    purchased_ids: set[str] = set()
    cart = snapshot.get("cart", {}).get("items") if snapshot and isinstance(snapshot.get("cart"), dict) else None
    if isinstance(cart, list) and all(
        isinstance(row, dict) and isinstance(row.get("product_id"), str)
        and type(row.get("quantity")) is int and row["quantity"] > 0 for row in cart
    ):
        cart_qty = cart_quantities(cart)
        purchased_ids = set(cart_qty)
        # selected_product_ids are treated as one unit each; compare against cart quantities.
        selection_matches = Counter(record.selected_product_ids) == cart_qty
        result["selection_cart_consistency"] = "consistent" if selection_matches else "mismatch"
        saved = Counter((row.product_id, row.quantity) for row in record.cart_items)
        actual = Counter((row["product_id"], row["quantity"]) for row in cart)
        result["recorded_cart_consistency"] = "consistent" if saved == actual else "mismatch"

    # Title review runs for every termination reason when catalog titles are available.
    # Purchased titles are excluded; empty carts flag any exact catalog title mention.
    if products and record.response_text:
        text = normalized(record.response_text)
        titles_purchased = {normalized(p.title) for pid, p in products.items() if pid in purchased_ids}
        for pid, product in sorted(products.items()):
            title = normalized(product.title)
            if pid not in purchased_ids and title not in titles_purchased and re.search(
                r"(?<!\w)" + re.escape(title) + r"(?!\w)", text
            ):
                result["response_title_review"].append({"product_id": pid, "title": product.title})

    result["claims"] = claim_audit(record, products)
    result.update(audit_prose_claims(record))
    return result


def audit_records(records, input_bytes: bytes | None = None):
    trials = [audit_trial(record) for record in records]
    # One shared definition of an unsupported claim, identical to the report's.
    claims = structured_claim_summary(records)
    prose = aggregate_prose_audits(trials)
    report = {
        "audit_version": "structured-claims-v2",
        "summary": {
            "trials": len(trials),
            "selection_cart_consistency": dict(Counter(t["selection_cart_consistency"] for t in trials)),
            "recorded_cart_consistency": dict(Counter(t["recorded_cart_consistency"] for t in trials)),
            **claims,
            "response_title_review_trials": sum(bool(t["response_title_review"]) for t in trials),
            **prose,
        },
        "limitations": [
            "This audit does not change benchmark success or compare agent performance.",
            "Structured claim checks cover declared scalar facts, evaluated at final-state time.",
            "Unsupported-claim rate is contradicted declared claims divided by declared claims that could be checked. Trials with no checkable claim stay out of that denominator.",
            "Prose claim contradiction rate is a separate advisory extraction of atomic product facts from the explanation, checked against the latest recorded get_listing observation, with final state only when no listing was recorded.",
            "The prose rate is contradicted prose facts divided by prose facts that could be checked. Trials with no extracted facts stay out of that denominator.",
            "Extraction misses aliases, implicit references, and facts that do not name a recorded product title.",
            "Exact off-cart title mentions require human review; alternatives and negation can be legitimate.",
            "Title review covers all termination reasons; purchased titles are excluded.",
        ],
        "trials": trials,
    }
    if input_bytes is not None:
        report["input_sha256"] = hashlib.sha256(input_bytes).hexdigest()
    return report


def load_trial_records(path: Path):
    raw = path.read_bytes()
    records = [
        TrialResult.model_validate_json(line)
        for line in raw.decode("utf-8-sig").splitlines() if line.strip()
    ]
    return records, raw


def audit_path(path: Path):
    records, raw = load_trial_records(path)
    return audit_records(records, input_bytes=raw)
