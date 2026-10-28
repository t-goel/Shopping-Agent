# Benchmark validation — rules-baseline pilot

This document reports the validation of the 15-task suite (`task-suite-v1`):
spec clarity, achievability, loader-enforced quality checks, preliminary
pilot results, and known limitations. Validation is agent-independent: we
probe the suite's *data* with (a) the authoring loader's recomputation and
(b) a deterministic structured-rules baseline (a member of the general class
"tool-calling agent that searches, filters on observable attributes, ranks by
the declared rule, and re-verifies before deciding"), not because the suite is
tuned to that baseline, but because a suite unsolvable by any competent
tool-caller would be unsolvable by anything. Nothing here depends on the
baseline's internals; a real agent evaluation (`agent/claude` path through the
same `run_trial`) uses the identical task files, budgets, and scorer.

Config pin: tasks are pinned to `catalog_version: "catalog-v2"` and recorded
as `example-v1`; the pilot uses the runner as-is (`runner_version: pilot-v1`,
`baseline_version: rules-v1`); per-run source hashes are recorded in each
trial record (`run_metadata.source_sha256`).

## 1. Pilot testing method

Two independent channels, both evaluator-side:

1. **Authoring-loader recomputation.** The task loader
   (`mock-store/server/state.py:load_examples`) re-derives every expected
   outcome from the catalog plus each task's scheduled mutations
   (`example_checks.expected_products`) and rejects the file on disagreement.
   This validates the suite *before any trial runs*: a task whose documented
   expected set is wrong cannot load, so the suite tests and the pilot run
   share a single source of ground truth.
2. **Deterministic rules baseline.** `src/shopping_agent/agent/rules.py`
   receives only `AgentInput` (request text + ranking rule) — parsed
   constraints are *not* handed to it as filters to copy; it implements the
   search/filter/rank/re-verify flow itself against the public API. Each
   trial is a fresh `Store.reset(task_id)` with the evaluator-scheduled
   mutations active, scored through `eval.scoring.score` against the live
   store snapshot (constraint ledger, ranking validity, cart contents, cart
   unit price vs. live state, claim-evidence audit).

Commands (Windows, from the repo root):

```
py -m pytest -q                          # PYTHONPATH=src;mock-store — 50 passed
py -m shopping_agent.cli run --output <out.jsonl> \
      --max-calls 20 --repetitions 3 --agent rules
```

The exact run is reproducible from the command above (deterministic agent;
timestamped observation fields in raw traces are the only varying output).
`validation-results.json` holds the machine-readable per-task aggregation used
for the paper tables (counts, termination reasons, call/duration distributions,
selected products, and run metadata including the pilot run's source-code
snapshot hash).

## 2. Task quality checks

We additionally tamper-tested the loader to confirm the quality checks bite
at authoring time, not just in tests:

- **Bad expected sets are rejected.** We created a copy of
  `sponsored_shoe_search` declaring the sponsored decoy `peak-quest-ultra` as
  its valid product; the loader refused it with
  `expected products ['peak-quest-ultra'], computed ['tarn-fell']`. The
  recomputation follows hard constraints and the declared ranking rule over
  mutation-adjusted catalog state, so this check covers constraint typos,
  ranking-rule mistakes, and expected-set drift in one stroke.
- **`catalog_version` is pinned.** Copying any task file with
  `catalog_version: "catalog-v1"` fails with `catalog version mismatch`,
  so tasks cannot silently bind to a different catalogue revision; expected
  sets always refer to the catalog they were authored against.
- **Mutation final-state expected sets.** For the four mutation tasks the
  authoring check applies mutations *before* computing the valid set, i.e.
  the expected set is the final store state after `after_observations: 1`,
  not the pre-mutation state. This is exactly why `duffel_price_drop`
  expects `headwater-duffel` ($92 after the drop) rather than
  `basalt-carryall` ($96, the pre-mutation winner).
- **Structural/contract checks** also pass at load: unknown constraint
  attributes, unknown expected products, unknown mutation targets, duplicate
  task IDs, non-mutating mutations, and outcome-kind/expected-set mismatches
  all raise at authoring time (unit-covered by `tests/test_contracts.py`,
  `tests/test_evaluation.py`, and the suite's own
  `test_expected_sets_recompute_from_catalog_and_mutations`).

## 3. Preliminary results — deterministic rules baseline

15 tasks × 3 repetitions = 45 trials; budget `--max-calls 20` (the same
path/scale the suite tests use, where the asserted cap is 13 calls),
60 s wall clock each, seed 498 ordering. **Result: 15/15 tasks, 45/45
trials successful.** Observed maximum across all trials: **11 tool calls**
(bags tasks), median 9 — the 20-call budget is never approached, and no
trial hit a timeout, an error, or an exhausted budget.

| Task (id) | Diff. | Expected kind | Ranking | Trials (pass) | Termination | Calls (med/max) |
|---|---|---|---|---|---|---|
| `cheapest_waterproof_bag` | easy | product | lowest_price | 3/3 | completed ×3 | 11 / 11 |
| `cheapest_waterproof_jacket` | easy | product | lowest_price | 3/3 | completed ×3 | 8 / 8 |
| `clarify_shoe_size` | easy | clarification | none | 3/3 | clarification_needed ×3 | 0 / 0 |
| `clarify_jacket_size` | medium | clarification | none | 3/3 | clarification_needed ×3 | 0 / 0 |
| `comfy_waterproof_bag` | medium | product | lowest_price | 3/3 | completed ×3 | 11 / 11 |
| `jacket_title_trap` | medium | product | lowest_price | 3/3 | completed ×3 | 8 / 8 |
| `sponsored_shoe_search` | medium | product | lowest_price | 3/3 | completed ×3 | 10 / 10 |
| `highest_rated_waterproof_shoe` | medium | product | highest_rating | 3/3 | completed ×3 | 10 / 10 |
| `no_big_waterproof_bag` | medium | no_valid_product | none | 3/3 | no_valid_product ×3 | 9 / 9 |
| `no_waterproof_under_50` | medium | no_valid_product | none | 3/3 | no_valid_product ×3 | 6 / 6 |
| `top_rated_waterproof_bag` | medium | product | highest_rating | 3/3 | completed ×3 | 11 / 11 |
| `duffel_price_drop` | hard | product | lowest_price | 3/3 | completed ×3 | 11 / 11 |
| `stock_replenished_shoe` | hard | product | lowest_price | 3/3 | completed ×3 | 10 / 10 |
| `price_change` | hard | no_valid_product | lowest_price | 3/3 | no_valid_product ×3 | 6 / 6 |
| `stock_change` | hard | no_valid_product | lowest_price | 3/3 | no_valid_product ×3 | 6 / 6 |

Selected products matched the loader-recomputed expected winners in every
successful product trial (e.g. `harbor-backpack` for both bags "comfy"/
"cheapest" tasks, `tarn-fell` for the sponsored search, `granite-hiker` for
the rating tie, `headwater-duffel` post-drop at $92.00, `cinder-hiker` \$69.00
after restock), and every scorebook ledger read `constraints_satisfied =
total_constraints`. Because the baseline is deterministic, the 3 repetitions
agree exactly on selection and call counts; differences are only wall-clock
sub-timings (median trial duration ≈ 0.019 s, in-process).

## 4. Difficulty calibration evidence

The suite tests (`tests/test_task_suite.py`) pin the designed mix, and the
pilot confirms it empirically:

- **Counts match design: 3 easy / 8 medium / 4 hard**, asserted by
  `test_suite_composition_and_difficulty_mix` and confirmed by the loader
  during the pilot (`task-summary.json` row parity is asserted too).
- **Success is achievable at every difficulty** (Section 3: 15/15), so the
  scale is anchored — 0% at any tier would indicate a task-authoring bug,
  not an agent limit.
- **Difficulty tracks required behavior, not baseline quirks.** The rules
  baseline's call counts are governed by category size (jackets 8, footwear
  10, bags 11) and are *flat across difficulty*: the 6-call `price_change`
  is hard while the 11-call `cheapest_waterproof_bag` is easy. Hardness in
  this suite comes from timing and adjudication (mid-trial mutations,
  soft-vs-hard precedence, sponsored/title decoys, declared-rule literalism),
  none of which a monotonically larger budget or more tool calls can buy.
- **The traps fire against naive shortcuts** (probes below), so medium task
  discrimination is real rather than incidental.

## 5. Adversarial probes — why the baseline succeeds, and what fails

Three pre-designed adversarial checks (all recorded in `task-suite.md`) were
probed against the actual pilot traces:

1. **Sponsored-first decoy (`sponsored_shoe_search`, medium).** The search
   API returns the sponsored item first: sequence 1 of the pilot trace shows
   `peak-quest-ultra` before any valid candidate — a keyword-stuffed title
   ("Waterproof Hiking Trail Running Shoe Deal"), `attributes.waterproof` =
   false, size `10`, while the request needs size `9` and true waterproofing.
   The baseline passes because it filters every result on *attributes* from a
   full listing read rather than position or title, then ranks by price
   (`tarn-fell`, $91). A weak agent that clicks the top result, or trusts
   title keywords over attributes, lands on a product failing three counts
   at once (size, waterproof, and ranking is undecidable).
2. **Soft preference vs. hard constraint (`comfy_waterproof_bag`, medium).**
   The store's highest-rated bag (`canyon-pack`, 4.67, 30 L, "most
   comfortable", cheapest in category at $58) is also the item that satisfies
   every soft signal in the request — and fails the hard
   `waterproof = true` constraint. The baseline passes because it never lets
   a non-listed preference or review sentiment re-enter eligibility;
   `harbor-backpack` ($64, 22 L) wins under `lowest_price`.
   A weak agent that lets "comfortable" out-vote "absolutely has to be
   genuinely waterproof" selects a non-waterproof product — precisely the
   near-miss the ledger is built to catch per-constraint.
3. **Mid-trial mutation recovery (`duffel_price_drop`, hard).** Trace
   evidence from the pilot: sequence 1 (search) shows `headwater-duffel`
   at $149.00; after `after_observations: 1` fires, sequence 5 and 10
   (`get_listing`) show $92.00; the final cart is `headwater-duffel` at
   unit price $92.00, matching the live store state, so the scorer's
   price-consistency check passes. The baseline recovers because it
   re-reads the full candidate set after its first observation *and*
   re-ranks before committing. A single-snapshot agent — or one that
   re-checks only its chosen candidate — commits to the pre-mutation winner
   (`basalt-carryall` at $96) and carts at the stale price; the scorer
   validates cart unit price against live state, so that cart fails even
   though "it looked right" at decision time. The complementary hard task
   `stock_replenished_shoe` shows the baseline re-checking an item that
   appeared out of stock ($69 `cinder-hiker`, stock 0 → restocked) and
   correctly reviving it; an agent that caches stock status from its first
   pass wrongly abstains.

## 6. Known limitations

- **Budget coupling.** The rules baseline's tool-call needs scale with
  category size (bags = 9 products → 11 calls); 20 leaves headroom but the
  choice itself is a benchmark parameter. The eval-protocol layer owns the
  production budget; we recorded observed maxima (11) so the coupling can be
  reasoned about explicitly rather than hidden.
- **Single-merchant, closed world.** Decoy resistance is measured against
  this suite's documented fixture taxonomy inside one store; cross-shop
  effects are out of scope by design.
- **Scripted clarification.** The scored signal is a question containing the
  declared anchor ("size"); no user simulation judges the question's
  phrasing or completeness.
- **No human inter-annotator reliability yet.** Difficulty labels and the
  quality checks are analysis + loader-recomputation, not IRR over multiple
  human annotators; the annotation protocol remains to be run.
- **`unsupported_claim_rate` is still null in reports.** The pilot records
  the field (baseline claims are all evidence-backed and the scorer audits
  them), but the metric is not yet exercised by an agent that actually emits
  unfounded claims; a weak-agent run will populate it in a later layer.
- **Determinism ceiling.** Identical repetitions of the baseline give no
  variance information; run-to-run numbers for stochastic agents require the
  repetitions machinery (`--repetitions`, seed) that this pilot already
  exercises, which we document rather than extrapolate.
- **Single-epoch, single-seed ordering.** Trials are shuffled with seed 498
  and the pipeline refuses to silently overwrite prior experiment outputs;
  only one ordering per repetition is used.
