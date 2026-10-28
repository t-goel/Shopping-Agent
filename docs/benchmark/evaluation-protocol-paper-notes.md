# Section 4 paper notes — evaluation protocol

Prose bullets for ICLR LaTeX section 4 (~0.5 page). No agent advocacy;
referenced metric names match `evaluation-protocol.md`, which carries the full
normative spec. Trim to what survives revision; suggested paragraph grouping:
scoring, metrics/aggregation, protocol & reproducibility.

## Scoring (para 1)

- Every success criterion is a rule over the agent's final output and the
  store's final live state; no agent-reported success signal is consulted.
  The scorer recomputes the hard-constraint candidate set from live prices and
  stock, so a mutation that invalidates the selected product fails the trial
  even if the agent never observed it.
- Three scored outcome kinds mirror the suite's expected-answer types: select
  (`product`), abstain (`no_valid_product`), and ask (`clarification`).
  Selection trials require a single selection from the ground-truth valid set
  under the declared ranking rule, an exactly-one-item cart matching the
  selection at quantity 1, and cart consistency with live state: the carted
  unit price must equal the product's final price, so a correct product id
  decided at a stale pre-mutation price still fails. Abstention trials require
  terminating with an explicit `no_valid_product` decision while the
  recomputed candidate set (from final state) is empty; an abstention issued
  without any product observation in `price_change` fails because the final
  state still contains the pre-mutation winner — whether the mutation has
  fired is decided by the store, not claimed by the agent. Clarification
  trials require the fixed terminal reason, no selection, an empty cart, and
  a response containing the underspecified axis's anchor.
- Every trial additionally maintains a per-constraint ledger over hard
  constraints: satisfied iff the selection is non-empty and every selected
  product matches the constraint under the typed comparators (`eq`, `gte`,
  `lte`, `contains`). A selection failing exactly one hard constraint at
  scoring time records $|C|-1$ of $|C|$ — this is the near-miss diagnostic.
  Trials terminated by budget exhaustion or crash fail outright, with the
  ledger recorded against the agent's final selection.
- Evaluator-scheduled mutations change live catalog state, applied by the
  store exactly once, immediately before the first interaction once the
  observation threshold is reached ($N{=}1$ in our suite); they are
  irreversible within the trial. The scorer's snapshot and every later
  observation see the post-mutation state, so stale-belief plans are
  penalized exactly at the point they diverge from reality.

## Metrics (para 2)

- Primary: task success rate (mean binary score over 45 trials = 15 tasks × 3
  repetitions, default configuration). Secondary: per-difficulty
  success rates over the fixed easy/medium/hard tiers; constraint
  satisfaction, averaged over selection-bearing (`product`-kind) trials of
  `constraints_satisfied / total_constraints`; termination-reason distribution
  over the fixed set
  (`completed`, `no_valid_product`, `clarification_needed`,
  `max_tool_calls_exceeded`, `timeout`, `unrecoverable_failure`), which
  separates wrong answers from budget-mediated failures; median tool calls and
  median / p95 wall-clock durations.
- Reserved but unreported in v1 (published as `null` rather than zero):
  unsupported-claim rate over the agent's claim/evidence audit, human
  judgment of response quality, and model cost. Token and cost fields exist
  in the per-trial schema for metered models to populate.

## Protocol (para 3)

- One trial = one fresh process against one freshly reset store instance;
  trials run strictly sequentially, and all counter and mutation state is
  held in a single process. Per trial the agent sees only the
  natural-language request with its declared constraints/preferences, the
  ranking rule, and the store's public API (`search`, product listing and
  reviews, cart write/read); expected outcomes, mutation schedules, and all
  `/internal/*` evaluator endpoints are withheld.
- Two budgets, declared per run and recorded in every trial's metadata: ≤20
  tool calls (the deterministic baseline needs ≈11 on the largest category,
  so 20 keeps recovery behavior in range) and a 60-second cooperative
  wall-clock deadline with a hard process-level backstop; exceeding either —
  or a worker crash — yields an explicit failure termination and a failed
  trial, rather than a silent partial score.
- Reproducibility: catalog version `catalog-v2` is pinned per task and per
  store snapshot; store state (catalog, cart, observation counter, mutation
  log) resets before every trial; mutation schedules are evaluator-only and
  applied exactly once under a recorded counter; task order is seeded and
  logged per repetition; every trial record carries a source hash, budgets,
  runner and baseline versions, and key package versions.
- Third parties integrate at one seam: implement the agent-protocol function
  (request plus ranking rule in, final output with a six-valued termination
  reason out) over the same four-tool store surface, with equivalent tool-call
  budget enforcement. Everything downstream — reset, budget
  enforcement, snapshotting, scoring, aggregation — stays evaluator-side, so
  an agent cannot touch ground truth except through tool use on the public
  surface.

## Reporting (para 4)

- One JSONL row per trial under a fixed, `extra="forbid"` schema (`TrialResult`):
  task and catalog versions, agent identity (with a nullable model id for
  non-LLM baselines), trial and repetition numbers, termination reason,
  binary success, constraint ledger counts, selection ids, cart items from
  live state, efficiency counters (tool calls, durations, optional tokens and
  cost), the full ordered tool trace, the evaluator's final-state snapshot,
  and the run's metadata block.
- Suggested main table: rows per agent, columns = overall / easy / medium /
  hard success rates, constraint satisfaction, a compact termination
  distribution (e.g. percent completed / percent timeout), median tool calls,
  median seconds. Include the claim-audit and cost columns only when
  populated rather than printing zeros.
