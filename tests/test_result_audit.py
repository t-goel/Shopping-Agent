import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from server.state import load_examples
from shopping_agent.eval.audit import audit_records, audit_trial
from shopping_agent.eval.runner import run_trial


@pytest.fixture
def completed():
    root = Path(__file__).resolve().parents[1]
    catalog, tasks = load_examples(tasks_path=root / "data/tasks/harness")
    return run_trial(catalog, tasks["cheapest_waterproof_jacket"])


def test_clean_trial_audit_does_not_mutate_or_rescore(completed):
    before = completed.model_dump_json()
    result = audit_trial(completed)
    assert result["selection_cart_consistency"] == "consistent"
    assert result["recorded_cart_consistency"] == "consistent"
    assert [c["status"] for c in result["claims"]] == ["supports", "supports"]
    assert completed.model_dump_json() == before


def test_final_state_overrides_agent_evidence(completed):
    # Keep the agent's original supporting evidence; mutate the authoritative snapshot.
    completed.final_state["products"]["ridge-shell"]["price"] = 110
    result = audit_trial(completed)
    price = next(c for c in result["claims"] if c["field"] == "price")
    assert price["status"] == "contradicts"
    assert price["observed_value"] == 110
    assert all(e.status == "supports" for e in completed.evidence)
    assert result["original_success"] is True  # Audit never rewrites historical scoring.


def test_cart_mismatch_and_quantity_are_detected(completed):
    completed.selected_product_ids = ["summit-shell"]
    completed.cart_items[0].quantity = 2
    result = audit_trial(completed)
    assert result["selection_cart_consistency"] == "mismatch"
    assert result["recorded_cart_consistency"] == "mismatch"


@pytest.mark.parametrize("snapshot", [None, {}, {"cart": {"items": None}}, {"cart": {"items": [{}]}}])
def test_missing_or_malformed_snapshot_is_not_a_pass(completed, snapshot):
    completed.final_state = snapshot
    result = audit_records([completed])
    assert result["summary"]["selection_cart_consistency"] == {"unassessable": 1}
    assert result["summary"]["structured_claim_contradiction_rate"] is None


def test_empty_claims_are_not_reported_as_zero_contradictions(completed):
    completed.claims = []
    summary = audit_records([completed])["summary"]
    assert summary["trials_with_claims"] == 0
    assert summary["structured_claim_contradiction_rate"] is None


def test_invalid_unknown_and_typed_claims(completed):
    completed.claims = [
        {"claim_id": "boolean", "product_id": "ridge-shell", "field": "waterproof", "value": 1},
        {"claim_id": "missing", "product_id": "ridge-shell", "field": "unknown", "value": True},
        {"claim_id": "absent", "product_id": "nonexistent", "field": "price", "value": 89},
        {"bad": "schema"},
    ]
    summary = audit_records([completed])["summary"]
    assert summary["structured_claims"] == {"supports": 0, "contradicts": 1, "unknown": 2, "invalid": 1}
    assert summary["assessable_claims"] == 1
    assert summary["structured_claim_contradiction_rate"] == 1


def test_off_cart_mentions_are_only_review_flags(completed):
    title = completed.final_state["products"]["summit-shell"]["title"]
    completed.response_text = "Do not buy " + title.upper() + "; I selected the other jacket."
    result = audit_trial(completed)
    assert result["selection_cart_consistency"] == "consistent"
    assert result["response_title_review"] == [{"product_id": "summit-shell", "title": title}]
    assert result["original_success"] is True
    completed.response_text = title + "XYZ"
    assert audit_trial(completed)["response_title_review"] == []


def test_cli_audits_utf8_without_api_key_and_preserves_file(completed, tmp_path):
    path = tmp_path / "trials.jsonl"
    completed.response_text = "Rain jacket — selected."
    path.write_text(completed.model_dump_json() + "\n", encoding="utf-8-sig")
    before = path.read_bytes()
    env = dict(os.environ)
    env.pop("ANTHROPIC_API_KEY", None)
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
    run = subprocess.run([sys.executable, "-m", "shopping_agent.eval.audit", str(path)],
                         capture_output=True, text=True, env=env, timeout=20)
    assert run.returncode == 0, run.stderr
    report = json.loads(run.stdout)
    assert len(report["input_sha256"]) == 64
    assert report["summary"]["trials"] == 1
    assert path.read_bytes() == before
