# Project Update 3: Billy's contribution

## Progress Summary

I extended the evaluation pipeline to preserve agent/model identity on failures and timeouts, record prompt and input provenance, and collect provider-reported token usage. I added per-task reporting and failure categories, prevented invalid comparisons between structured and natural-language inputs, and ran both the structured pilot and the new natural-language benchmark.

## Current Status — Evaluation

All 62 automated tests passed, including seven new regression tests for experiment attribution, token accounting, preflight validation, and reporting. The five-task structured rules pilot passed 15/15 trials (three repetitions per task). Its median tool count was 6, median agent runtime was 0.0150 seconds, and p95 was 0.0160 seconds. These local API measurements exclude worker startup/scoring and are not browser or LLM latency measurements. Very short timings can round to zero on this host.

The live Claude run completed all 30 trials across the 10-task suite-v4 benchmark on catalog-v2, using claude-sonnet-4-5, seed 498, a 20-tool-call limit, and a 60-second trial timeout. It succeeded on 1/30 trials (3.3%). Median tool calls were 4.0; median agent runtime was 10.61 seconds and p95 was 19.88 seconds. All failures remain in the denominator. There are 10 distinct tasks, not 30 independent tasks.

Provider-reported input/output tokens total 286688 across 30 trials with complete measurements (a null total means incomplete usage). No dollar cost is estimated. The structured pilot and natural-language suite use different tasks and input assistance, so their success rates are reported separately and are not a controlled agent comparison.

## Challenges and Solutions

The runner previously labeled forcibly interrupted Claude trials as rules-agent trials and omitted model/prompt identifiers. I fixed that attribution and added tests covering timeout and error paths. I also added validation that rejects the structured-only rules agent on natural-language tasks before creating output records.

The live run exposed agent failures rather than evaluator crashes. Error types were {'JSONDecodeError': 23, 'RuntimeError': 2}; observed failure categories were {'unrecoverable_failure': 25, 'incorrect_abstention': 3, 'hard_constraint_violation': 1}.

1. Final-output parsing: the first cheapest-jacket trial failed with JSONDecodeError after two tool calls. The current records do not retain raw model text, so we cannot identify the exact offending output. Add validated structured output and retain diagnostic model responses before interpreting this as a reasoning failure.
2. Incorrect abstention: in the first size-9 footwear trial, the agent issued five increasingly broad searches that all returned empty results and incorrectly abstained. The store matches every query term literally, so the agent's search wording can miss catalog items. Test a public-tool category fallback without revealing evaluator answers.
3. Recommendation/cart mismatch: in repetition 2 of `implied_monsoon_kit_single_sku`, the response recommended the Harbor Dry Pack, but the cart contained `basalt-carryall` and only three of five hard constraints passed. The current postprocessing reranks candidates even when the NL input has no supplied ranking rule; its fallback orders by product ID. This is a plausible mechanism from code inspection, not a replay-proven root cause. Add a focused regression and fix the agent's interpreted-constraint/ranking path before the next comparison.

These agent problems are documented and remain to be fixed; evaluator changes do not imply the shopping agent now passes the NL benchmark.

## Next Steps

- Billy: share the per-task results and representative traces with Ronit; rerun the same frozen suite after the agreed agent fixes, retaining these results as the reference run.
- Ronit and Billy: verify the interpretation-stage branch, add a supported clarification outcome and validated final-output handling, and test search fallback against the public catalog API without exposing hidden evaluator constraints.
- Billy and Tim: define browser action/time budgets before collecting browser results; keep API and browser measurements separate.

## Questions and Help Needed

The live API connection now works. The remaining coordination need is the exact commit containing Ronit's claimed interpretation/reliability work. The main-branch implementation used in this run does not contain that phase. Resolve the contradictory interpretation claims and unfinished sentence in the group draft before submission.

## Individual Contributions

Billy: Improved evaluation attribution, reproducibility metadata, token tracking, and per-task reporting; added seven regression tests; and evaluated the structured pilot and 10-task natural-language benchmark with preserved traces and failure analysis.

## Evidence and limitations

- `docs/pilot/rules-update-3.jsonl` and `summary-update-3.json`: structured pilot.
- `docs/pilot/claude-update-3.jsonl`, `claude-summary-update-3.json`, and `claude-report-update-3.md`: live NL experiment.
- `docs/pilot/environment-update-3.txt`: exact Python dependency versions.
- Source base commit: `1436a0c89f871091fba65833450d8f7c53d91848` with the evaluation changes in this contribution; the exact evaluated Python source is identified by `736cb04e114ad7f30b527df4ab6434426f07ff5c9d992d709364eacae3b39f0a`. Task/catalog/prompt hashes are also recorded in every trial.
- The simulated HTTP test verifies integration and token aggregation; the 30-trial file contains actual API calls. These are separate evidence sources.
- One existing Starlette/HTTPX deprecation warning remains. No browser trials, human ratings, or independent factual-claim annotations were performed.
