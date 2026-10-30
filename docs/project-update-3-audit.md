# Billy's independent result-audit contribution

## Paste into Progress Summary

We added an independent audit of saved evaluation results that checks selected products against the final cart and verifies structured product claims against the final store state. It also flags response text that mentions products outside the cart for manual review. These checks are separate from the agent's own verification and leave the benchmark's success scores unchanged.

## Paste into Current Status — Evaluation

The independent result audit is implemented and tested. All 69 automated tests passed, including 11 new audit tests covering stale claims, cart mismatches, missing evidence, and report generation. Auditing saved historical traces identified two incorrect product claims and one response requiring review; these findings concern an earlier agent version, not the newer version's reported 20/20 run.

## Paste into Challenges and Solutions

A final cart can agree with the agent's selected product ID even when the written recommendation describes another product. In an earlier trace, the cart contained a product priced at $96 with 30-liter capacity, but the associated claims stated $64 and 22 liters, and the response named a different product. We addressed this evaluation gap by checking declared facts against the saved final store state rather than trusting the agent's own supporting evidence. Product-name mentions outside the cart are flagged for manual review because a response may legitimately discuss alternatives.

## Paste into Next Steps

Billy will audit the latest successful-agent traces, review flagged recommendation/cart discrepancies, and report factual consistency alongside task success. Missing claims and missing snapshots will remain explicitly unassessed rather than being counted as correct.

## Paste into Individual Contributions

Billy: Implemented an independent audit of saved evaluation results to check cart consistency and product claims against final store state, added 11 regression tests, and validated the audit on historical agent traces.

## Ownership and scope

The current group update attributes agent reliability and benchmark runs to Tim, natural-language interpretation and typed tools to Ronit, and benchmark content and storefront clutter to Neel. Neel's terminal-report PR #13 is merged. This contribution is a separate read-only audit command; it does not modify agent behavior, task design, scoring, or the terminal report.

## Reproduce

From the repository root, after installing requirements-dev.txt:

```powershell
py eval.py audit path/to/trials.jsonl
py -m pytest -q
```

The command prints JSON and never modifies its input. It needs no API key and makes no model calls. Each report includes the input file's SHA-256 digest. After `py -m pip install -e .`, `shopping-agent audit` works the same way.

## Verified evidence

- Base: merged main commit c75dd0e (includes Neel's terminal reporting).
- Full suite: 69 passed, one existing Starlette/HTTPX deprecation warning.
- Historical Claude traces from PR #14: 30 trials, only two containing structured claims. Of six assessable claims, four were supported and two contradicted final state. One trial was flagged for off-cart product-title review.
- Historical rules traces from PR #14: 15 trials, only three containing structured claims. All six assessable claims were supported; no off-cart title flags.
- Both sets had selected IDs and recorded cart entries consistent with final cart entries. That includes empty selections/carts on failed trials; it does not establish task success or factual accuracy.
- In `implied_monsoon_kit_single_sku`, repetition 2, the structured price/capacity claims for `basalt-carryall` contradicted final facts and the response named `harbor-backpack` (Harbor Dry Pack 22L).

Reports are saved in `docs/audit/`. Their input traces are the older `docs/pilot/claude-update-3.jsonl` and `rules-update-3.jsonl` on the `billy/evaluation-update-3` branch (PR #14). These are diagnostic historical evidence; the current group's newer 20/20 run was not available in the inspected repository and has not been audited here.

## Limits

The contradiction rate applies only to declared scalar claims with known final facts, not all prose. Unsupported types, missing facts, and absent snapshots are not counted as verified. Final-state checks can flag a claim that was true earlier in a changing environment. Exact title matching misses aliases and implicit references, and can flag legitimate comparisons or negations; flags require human review. This is an automated consistency audit, not an independent human factual-claim annotation study.
