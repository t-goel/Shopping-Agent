"""Read-only audits of saved trials against final state, not agent evidence."""

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path

from pydantic import ValidationError

from shopping_agent.comparison import matches
from shopping_agent.contracts import Constraint, Product, TrialResult
from shopping_agent.interfaces import Claim


def normalized(text):
    return " ".join(text.casefold().split())


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
    products = {}
    if snapshot and isinstance(snapshot.get("products"), dict):
        for pid, value in snapshot["products"].items():
            try:
                product = Product.model_validate(value)
                if product.product_id == pid:
                    products[pid] = product
            except (ValidationError, TypeError):
                pass  # Missing/malformed facts cannot support a claim.

    cart = snapshot.get("cart", {}).get("items") if snapshot and isinstance(snapshot.get("cart"), dict) else None
    if isinstance(cart, list) and all(
        isinstance(row, dict) and isinstance(row.get("product_id"), str)
        and type(row.get("quantity")) is int and row["quantity"] > 0 for row in cart
    ):
        cart_ids = Counter(row["product_id"] for row in cart)
        selection_matches = Counter(record.selected_product_ids) == cart_ids
        result["selection_cart_consistency"] = "consistent" if selection_matches else "mismatch"
        saved = Counter((row.product_id, row.quantity) for row in record.cart_items)
        actual = Counter((row["product_id"], row["quantity"]) for row in cart)
        result["recorded_cart_consistency"] = "consistent" if saved == actual else "mismatch"

        # Exact title mentions are review candidates, never automatic factual errors.
        # Alternatives and negations can legitimately mention products outside a cart.
        if record.termination_reason == "completed":
            text = normalized(record.response_text)
            titles_in_cart = {normalized(p.title) for pid, p in products.items() if pid in cart_ids}
            for pid, product in sorted(products.items()):
                title = normalized(product.title)
                if pid not in cart_ids and title not in titles_in_cart and re.search(
                    r"(?<!\w)" + re.escape(title) + r"(?!\w)", text
                ):
                    result["response_title_review"].append({"product_id": pid, "title": product.title})

    for index, raw in enumerate(record.claims):
        entry = {"index": index, "status": "invalid", "observed_value": None}
        try:
            claim = Claim.model_validate(raw)
        except (ValidationError, TypeError):
            result["claims"].append(entry)
            continue
        entry.update(claim_id=claim.claim_id, product_id=claim.product_id,
                     field=claim.field, claimed_value=claim.value, status="unknown")
        product = products.get(claim.product_id)
        if product is not None:
            value = (getattr(product, claim.field) if claim.field in type(product).model_fields
                     else product.attributes.get(claim.field))
            if type(value) in (str, int, float, bool):
                entry["observed_value"] = value
                entry["status"] = "supports" if matches(product, Constraint(
                    attribute=claim.field, operator="eq", value=claim.value)) else "contradicts"
        result["claims"].append(entry)
    return result


def audit_records(records):
    trials = [audit_trial(record) for record in records]
    claims = Counter(c["status"] for trial in trials for c in trial["claims"])
    assessed = claims["supports"] + claims["contradicts"]
    return {
        "audit_version": "final-state-v1",
        "summary": {
            "trials": len(trials),
            "selection_cart_consistency": dict(Counter(t["selection_cart_consistency"] for t in trials)),
            "recorded_cart_consistency": dict(Counter(t["recorded_cart_consistency"] for t in trials)),
            "structured_claims": {s: claims[s] for s in ("supports", "contradicts", "unknown", "invalid")},
            "assessable_claims": assessed,
            "structured_claim_contradiction_rate": claims["contradicts"] / assessed if assessed else None,
            "trials_with_claims": sum(bool(t["claims"]) for t in trials),
            "response_title_review_trials": sum(bool(t["response_title_review"]) for t in trials),
        },
        "limitations": [
            "This audit does not change benchmark success or compare agent performance.",
            "Claim checks cover only declared scalar facts, evaluated at final-state time.",
            "Missing facts/snapshots are unassessable; absent claims are not verified prose.",
            "Exact off-cart title mentions require human review; alternatives and negation can be legitimate.",
            "No title flags does not prove prose consistency; aliases and implicit references are not parsed.",
        ],
        "trials": trials,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="Saved trial JSONL; no API key needed")
    args = parser.parse_args()
    raw = args.input.read_bytes()
    records = [TrialResult.model_validate_json(line) for line in raw.decode("utf-8-sig").splitlines() if line.strip()]
    report = audit_records(records)
    report["input_sha256"] = hashlib.sha256(raw).hexdigest()
    print(json.dumps(report, indent=2, ensure_ascii=True))


if __name__ == "__main__":
    main()
