"""Read-only summaries; unavailable measurements stay null."""
import math
from collections import Counter
from statistics import median

from shopping_agent.contracts import TrialResult


def summarize(records: list[TrialResult]):
    def aggregate(rows):
        times = sorted(r.duration_seconds for r in rows)
        product_rows = [r for r in rows if r.expected_kind == "product" and r.total_constraints]
        return {
            "trials": len(rows), "successful": sum(r.is_successful for r in rows),
            "success_rate": sum(r.is_successful for r in rows) / len(rows) if rows else None,
            "product_constraint_satisfaction": (
                sum(r.constraints_satisfied / r.total_constraints for r in product_rows) / len(product_rows)
                if product_rows else None),
            "termination_reasons": dict(Counter(r.termination_reason for r in rows)),
            "median_duration_seconds": median(times) if times else None,
            "p95_duration_seconds": times[math.ceil(.95 * len(times)) - 1] if times else None,
            "median_tool_calls": median(r.tool_calls for r in rows) if rows else None,
            "unsupported_claim_rate": None, "human_rating": None,
            "model_cost_usd": None, "model_tokens": None,
        }
    return {"overall": aggregate(records), "by_difficulty": {
        tier: aggregate([r for r in records if r.difficulty == tier])
        for tier in ("easy", "medium", "hard")
    }}


def read_records(path):
    return [TrialResult.model_validate_json(line) for line in path.read_text().splitlines() if line.strip()]
