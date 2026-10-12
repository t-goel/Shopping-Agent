# Project Update 2 — draft for October 13, 2026

This draft covers verified repository progress. Before submitting the group PDF, add each teammate's actual progress, complete all four names and actual contribution statements, and review the combined update. Do not present assigned future work as completed work.

## 1. Progress Summary

We implemented typed API tools, deterministic hard-constraint and factual-claim verification, a structured-request rules baseline, and an independent evaluation runner. The runner resets the mock store between trials, enforces tool-call and wall-clock budgets, scores final state/cart contents, and records JSONL traces. Added regression tests cover price/stock mutations, recovery to replacements, and incorrect or stale outcomes.

## 2. Current Status

Benchmark: five of the required 10 original task definitions are authored (50% by task count), spanning 1 easy, 2 medium, and 2 hard tasks. The six-product catalog and existing mock storefront/API remain functional. The authored tasks still need independent review and expansion; task count is not a measure of overall benchmark quality/completion.

Agent implementation: the deterministic rules baseline is implemented and tested. It receives supplied structured constraints and ranking rules; natural-language parsing, LLM planning, model baselines, ablations, and browser-agent execution remain pending. No percentage is claimed for the complete agent because its remaining components have different sizes.

Evaluation: all 36 automated tests passed on Python 3.12. Regression coverage includes 20 additional test cases beyond the 16 original tests. The five existing tasks were run three times each with seed 498: **15/15 successful trials**. Median public tool calls: **6**. Median agent duration: **0.0143 seconds**; nearest-rank p95: **0.0172 seconds**. These are local in-process API timings, excluding worker startup and scoring; they are not LLM/browser latency measurements.

| Task | Successful trials | Outcome | Calls per trial |
|---|---:|---|---:|
| `cheapest_waterproof_jacket` | 3/3 | completed | 8 |
| `clarify_jacket_size` | 3/3 | clarification_needed | 0 |
| `no_waterproof_under_50` | 3/3 | no_valid_product | 6 |
| `price_change` | 3/3 | no_valid_product | 6 |
| `stock_change` | 3/3 | no_valid_product | 6 |

The clarification task supplies the exact question in `request.clarification_needed`; its 3/3 results measure instruction routing, not ambiguity detection. Expected outcome objects are withheld, but these structured inputs provide assistance. Before comparing LLM conditions, we will use a common input policy or evaluate ambiguity detection separately.

Product-outcome hard-constraint satisfaction was 100% across three trials of the single product-selection task. The remaining outcomes were abstentions or clarification and are not included in this metric. Claim-audit rate and human ratings are unmeasured; model tokens/cost are not applicable to this baseline. Fifteen trials repeat only five tasks, so these results demonstrate pilot plumbing and objective outcomes, not general shopping ability, comparative improvement, or statistical significance.

## 3. Challenges and Solutions

Search observations become stale when prices or stock mutate. The baseline re-reads listings and revalidates the selected item before cart addition. A review found that a late price increase could leave an item eligible but make another cheaper. The fix updates that observation and reranks before cart addition; a regression confirms that a $96 item is replaced by a $95 alternative while both remain under the $100 budget. The scorer independently uses final live state; it does not trust agent-reported success. Test-only catalogs demonstrate successful recovery to another eligible item when the original becomes invalid.

Agents receive the parsed request, ranking rule, and allowlisted tools. Expected sets, task mutations, reset, and state snapshots remain evaluator controls. The supplied clarification directive is an intentional pilot shortcut, so these results do not claim unassisted ambiguity detection. Ordinary tools operate through the existing FastAPI routes, rather than directly reading store state.

We distinguish stopping rules from quality targets: trials have 10 attempted public tool calls and a 60-second execution limit; 15-second latency remains a performance target. A parent process can terminate a blocked agent. Errors and timeouts are unsuccessful and stay in the success-rate denominator. The installed Starlette version emits an HTTPX deprecation warning; current tests and trials pass, with exact dependency versions preserved for reproduction.

## 4. Next Steps

- Pipeline owner: review and integrate this contribution and support shared-interface integration.
- LLM owner: implement an original model-backed loop against the shared interfaces, then single-prompt/ReAct baselines and ablations.
- Benchmark owner: add five original tasks for the final 3 easy / 3 medium / 4 hard split, with broader products, ranking tradeoffs, and recoverable mutations.
- Browser/update owner: complete a small Playwright storefront smoke test, collect everyone's verified contribution statements, and finalize the group update PDF. Broader browser tool integration follows the deadline.

These tasks can proceed in parallel. Shared interface review comes first; LLM evaluation depends on tool/runner integration, and the final update depends on actual results. Details are in `parallel-handoff.md`.

## 5. Questions and Help Needed

The evaluation-plan feedback still requires a consistent definition for intermediate results and conflicting overall criteria; a predefined paired statistical analysis; a consistent repeat-count/choice-agreement protocol; independent factual-claim annotations; and an anchored human-rating rubric. Resolve these before comparative runs, not after seeing their results. No blocker remains for the deterministic pilot.

## 6. Individual Contributions

- Pipeline contributor (name pending): Implemented shared agent/tool interfaces, deterministic verification, the rules baseline, independent scoring and bounded runner, regression tests, and preserved the 15-trial pilot results.
- LLM contributor: name and actual weekly contribution pending team confirmation.
- Benchmark contributor: name and actual weekly contribution pending team confirmation.
- Browser/update contributor: name and actual weekly contribution pending team confirmation.

Evidence: `pilot/rules-2026-10-12-reviewed.jsonl`, `pilot/summary-2026-10-12-reviewed.json`, and `pilot/environment-2026-10-12.txt`. Each record includes task/catalog versions, seed/task order, source-code hash, limits, observations, final state, and outcome.
