from pathlib import Path

from server.state import load_examples
from shopping_agent.contracts import Product
from shopping_agent.eval.audit import audit_records, audit_trial
from shopping_agent.eval.prose_claims import (
    audit_prose_claims,
    extract_prose_claims,
    unsupported_claim_rate,
)
from shopping_agent.eval.report import summarize
from shopping_agent.eval.runner import run_trial


def _jacket():
    catalog, _ = load_examples()
    return {product.product_id: product for product in catalog.products if product.product_id == "ridge-shell"}


def test_extracts_price_stock_and_attribute_near_title():
    products = _jacket()
    text = "Ridge Rain Shell is $89.00, size M, and in stock. It is waterproof."
    claims = {(c.field, c.value) for c in extract_prose_claims(text, products)}
    assert ("price", 89.0) in claims
    assert ("stock_status", "in_stock") in claims
    assert ("size", "M") in claims
    assert ("waterproof", True) in claims


def test_negation_and_unrelated_price_are_not_support_for_free():
    products = _jacket()
    text = "Ridge Rain Shell is not waterproof and not in stock. Budget is $20."
    claims = {(c.field, c.value) for c in extract_prose_claims(text, products)}
    assert ("waterproof", False) in claims
    assert ("stock_status", "in_stock") not in claims
    assert ("price", 20.0) not in claims


def test_prose_audit_uses_latest_get_listing_not_search_or_title_echo():
    root = Path(__file__).resolve().parents[1]
    catalog, tasks = load_examples(tasks_path=root / "data/tasks/harness")
    record = run_trial(catalog, tasks["cheapest_waterproof_jacket"])
    record.response_text = (
        "I picked Ridge Rain Shell at $89.00, size M, waterproof, rated 4.5, with 4 units left."
    )
    audit = audit_prose_claims(record)
    by_field = {item["field"]: item for item in audit["prose_claims"]}
    assert by_field["price"]["status"] == "supports"
    assert by_field["price"]["source"] == "get_listing"
    assert by_field["size"]["status"] == "supports"
    assert by_field["stock"]["status"] == "supports"
    assert by_field["rating"]["status"] == "supports"
    assert by_field["waterproof"]["status"] == "supports"
    assert audit["unsupported_claim_rate"] == 0

    record.response_text = "Ridge Rain Shell costs $40 and is out of stock."
    contradicted = audit_prose_claims(record)
    statuses = {item["field"]: item["status"] for item in contradicted["prose_claims"]}
    assert statuses["price"] == "contradicts"
    assert statuses["stock_status"] == "contradicts"
    assert contradicted["unsupported_claim_rate"] == 1


def test_stale_search_row_does_not_support_a_later_listing():
    root = Path(__file__).resolve().parents[1]
    catalog, tasks = load_examples(tasks_path=root / "data/tasks/harness")
    record = run_trial(catalog, tasks["price_change"])
    record.response_text = "Ridge Rain Shell is $89."
    audit = audit_prose_claims(record)
    price = next(item for item in audit["prose_claims"] if item["field"] == "price")
    assert price["status"] == "contradicts"
    assert price["observed_value"] == 109
    assert price["source"] == "get_listing"


def test_missing_explanation_facts_leave_the_rate_null():
    root = Path(__file__).resolve().parents[1]
    catalog, tasks = load_examples(tasks_path=root / "data/tasks/harness")
    record = run_trial(catalog, tasks["cheapest_waterproof_jacket"])
    record.response_text = "Nothing in the catalog fits."
    assert unsupported_claim_rate([record]) is None
    summary = audit_records([record])["summary"]
    assert summary["unsupported_claim_rate"] is None
    assert summary["assessable_prose_claims"] == 0

    # The compact report uses the verifier's structured claims, not a prose regex:
    # contradictory prose alone cannot relabel supported structured evidence.
    record.response_text = "Ridge Rain Shell is $40."
    report = summarize([record])
    assert report["overall"]["unsupported_claim_rate"] == 0
    contradicted = record.model_copy(deep=True)
    contradicted.evidence = [
        item.model_copy(update={"status": "contradicts"}) for item in record.evidence
    ]
    assert summarize([contradicted])["overall"]["unsupported_claim_rate"] == 1
    assert "unsupported-claim rate" in __import__(
        "shopping_agent.eval.report", fromlist=["markdown_report"]
    ).markdown_report([record]).casefold()


def test_audit_trial_keeps_structured_claims_and_adds_prose():
    root = Path(__file__).resolve().parents[1]
    catalog, tasks = load_examples(tasks_path=root / "data/tasks/harness")
    record = run_trial(catalog, tasks["cheapest_waterproof_jacket"])
    record.response_text = "Summit Rain Shell is $119."
    before = record.model_dump_json()
    result = audit_trial(record)
    assert [claim["status"] for claim in result["claims"]] == ["supports", "supports"]
    prose = next(item for item in result["prose_claims"] if item["product_id"] == "summit-shell")
    assert prose["status"] == "supports"
    assert record.model_dump_json() == before
    assert audit_records([record])["audit_version"] == "prose-observations-v1"


def test_products_are_real_contracts():
    products = _jacket()
    assert isinstance(next(iter(products.values())), Product)
