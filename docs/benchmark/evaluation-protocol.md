# Evaluation protocol — scoring, aggregation, and reporting

This document specifies how any agent is scored on this benchmark, independent of
our agent implementation. It concerns the *evaluation protocol* only (section 4
of the paper): scoring rules, aggregation, per-trial reporting, and
reproducibility controls. The task suite itself is specified in `task-suite.md`
(why the catalog contains what it does, in `catalog-design.md`; what prior
benchmarks measure, in `related-work.md`). Nothing here requires our LLM agent;
scoring depends only on (a) the agent's final declared output, (b) the final
live state of the mock store, and (c) evaluator-owned ground truth from
`data/tasks/*.json`.

All rules below are implemented by the evaluator code and tests:

| Concern | Implementation |
|---|---|
| Binary success, constraint ledger | `src/shopping_agent/eval/scoring.py` (`score`) |
| Per-trial record, budgets, process isolation | `src/shopping_agent/eval/runner.py` |
| Aggregation and summaries | `src/shopping_agent/eval/report.py` (`summarize`) |
| Per-trial and run contracts | `src/shopping_agent/contracts.py` (`TrialResult`, `TaskDefinition`) |
| Mock store API, reset, mutation schedule | `mock-store/server/app.py`, `mock-store/server/state.py` |
| Suite runs and reports | `src/shopping_agent/cli.py` |

Companion for section 4 drafting: `evaluation-protocol-paper-notes.md`.

## 1. Units of evaluation

A **trial** is one agent pass over one task, executed sequentially in a fresh
process against a freshly reset store instance. A **run** is one sweep of all
15 tasks. A **repetition** is a numbered trial per task within a run; the
reference protocol uses **1 run × 3 repetitions per task** (`repetitions=3`),
giving 45 trials total. Trials within a run execute strictly sequentially: the
in-memory store supports one live cart, so parallel trials must each own their
own store process (the reference runner does this via `multiprocessing` spawn
per trial).

Per trial the runner:

1. Creates a private `Store(catalog, {task_id: task})` and calls `reset(task_id)`
   — catalog restored, cart emptied, observation counter and applied-mutation
   set cleared.
2. Hands the agent only `AgentInput` (the natural-language `request` with its
   typed constraints/preferences, and the `ranking_rule`). Expected outcomes,
   mutation schedules, catalog file paths, and the constraint interpretation
   beyond the request text are never exposed.
3. Wraps the agent's tool surface in a budget enforcer (§4) and enforces the
   wall-clock and process deadlines.
4. Takes the ground-truth snapshot (`Store.snapshot()`) and scores it against
   the agent's final output (§3). The agent reports `selected_product_ids`,
   `response_text`, optional `claims`, and a `termination_reason`; whether the
   trial succeeds is decided **only by the evaluator from the live final state**,
   never from agent-reported success.

## 2. Metrics

Per trial the evaluator records all of the following (schema below, §5):

| Metric | Status | Definition |
|---|---|---|
| Task success | **required (primary)** | Binary, scored per §3 from the final live state. |
| Hard-constraint satisfaction | **required (secondary)** | Ledger over hard constraints: `constraints_satisfied / total_constraints` per trial (§3.1). |
| Termination reason | **required** | Exactly one of the six-value set in §3. Distribution over trials is reported; it explains *how* failures happen, not just whether. |
| Tool calls used | **required** | Count of tool invocations, including cart actions and calls that errored (§4). |
| Duration | **required** | Wall-clock seconds from agent start to final scoring input. |
| Claim-evidence audit | **optional (null today)** | `unsupported_claim_rate` is a planned metric over the agent's `claims` against its emitted `evidence`; the reference implementation does not yet compute it and reporting code exposes `null` until it exists. Do not invent numbers; report "not computed" when absent, never 0. |
| Human rating | **optional (null today)** | Reserved for a future response-quality study (`human_rating`); `null` today. |
| Cost and tokens | **optional (null today)** | `model_cost_usd`, `input_tokens`, `output_tokens` exist in the schema for metered models; `null` when the runner's current baseline (deterministic rules) reports none. Third parties with metered models are encouraged to populate these from their own meters. |

## 3. Scoring rules (exact)

The scorer is a pure function of the task, the agent's final `AgentOutput`, and
the store snapshot — the final **live** state: post-mutation product prices and
stock, plus the committed cart. Nothing else participates.

### 3.1 Hard-constraint ledger

Let `C` be the task's hard constraints (`hard: true`; soft constraints and
preferences do not enter scoring). For constraint `c`, ledger entry:

- **satisfied** iff the agent's selection is non-empty **and** every selected
  product id exists in the live catalog **and** the product matches `c` under
  the typed comparators (`eq`, `gte`, `lte`, `contains`; a missing attribute is
  a non-match).
- Otherwise **not satisfied**. A bogus product id or a multi-product selection
  that fails the constraint on any member counts as not satisfied.

`total_constraints = |C|`; `constraints_satisfied` is the count above. A
selection that fails *any* hard constraint gets at most `|C| − 1` satisfied —
this is the near-miss diagnostic. The ledger is recorded for every trial but is
reported in aggregate only over `product`-kind tasks (§6); a correct
`no_valid_product` or clarification has an empty selection and therefore
trivially 0/|C| satisfied — do not interpret that as failing every constraint.

### 3.2 Failure terminations are automatic fails

If `termination_reason ∈ {timeout, max_tool_calls_exceeded,
unrecoverable_failure}`, the trial **fails** with no further criteria
evaluated. The constraint ledger is still recorded (scored against the agent's
final selection, usually empty). These three reasons mean the trial hit a
budget or crashed rather than finishing with an outcome.

The three *successful-path* terminations are `completed`, `no_valid_product`,
and `clarification_needed` — and each is only valid for the matching expected
outcome kind (§3.3–§3.5). A trial that reports the right reason but leaves a
wrong world (e.g. a carted product on an abstention task) still fails on the
state criteria.

### 3.3 `product` tasks

Scoring recomputes the candidate set from the **final live state**:

1. **Candidates** = live products with `stock > 0` matching **all** hard
   constraints.
2. **Ranked** candidates by the task's `ranking_rule`:
   - `lowest_price`: keep only candidates attaining the minimum live `price`.
   - `highest_rating`: keep only candidates attaining the highest arithmetic
     mean review rating; a product with no reviews ranks worst (mean −1.0),
     below every reviewed product. Exact ties after ranking all count.
   - `none`: all candidates remain.
3. **Valid ids** = ranked candidates ∩ the task's authored `valid_product_ids`
   (authored ground truth, loader-validated against the catalog at task-author
   time).
4. **Success** iff **all** of:
   - `termination_reason == "completed"`;
   - exactly **one** selected product id, and it is in valid ids;
   - the cart contains **exactly one item** with that product id, quantity 1,
     tagged `in_stock` true;
   - cart consistency: the carted **unit price equals the live final price** of
     the selection, and the cart total equals that unit price (× quantity).
     The cart is validated against the store's own final bookkeeping, so
     deciding from a stale pre-mutation price disqualifies the trial even when
     the product id happens to be correct (`duffel_price_drop` fails every
     agent that carts the stale $149 price).

Note what success does **not** require: choosing among tie members is free
(either tie member of `highest_rated_waterproof_shoe` scores); the *response
text* is not parsed for product tasks; no assumption is made about which tool
calls were used, within budget.

### 3.4 `clarification` tasks

Success iff **all** of:

- `termination_reason == "clarification_needed"`;
- **no** selected product ids;
- **empty** cart (the store's `reset` baseline; any carted item disqualifies);
- the response text contains, case-insensitively, the task's
  `expected.question_contains` anchor (for all current tasks, `size` — the
  underspecified axis stated in `task-suite.md`).

Clarification is scored as one scripted behavior, not a user simulation: the
anchor check asks "did the agent ask about the axis the request actually
underspecifies," which is deterministic.

### 3.5 `no_valid_product` tasks

Success iff **all** of:

- `termination_reason == "no_valid_product"`;
- the **candidate set recomputed from the final live state is empty** — i.e.
  abstention must be correct against post-mutation ground truth, not merely
  asserted. Because the scoring snapshot also applies any due mutation, a
  correct abstention rests on the mutation having actually fired: in
  `price_change`, if the agent made fewer than `after_observations` (here 1)
  product reads, the mutation is still pending even at snapshot time, the
  final state retains a valid candidate, and the abstention scores as failure
  — abstention must be reached *in the world the mutation produced*;
- **no** selected product ids;
- **empty** cart.

### 3.6 How mutations affect final-state scoring

Every mutation is evaluator-scheduled in the task file, applied by the store,
and **owned by the evaluator**: agents are never told, in any channel
available to them, when or whether a mutation occurred. Mechanics (all in
`mock-store/server/state.py`):

- The store maintains a per-trial observation counter. A **product
  observation** is one `search` or product-listing (incl. reviews) read; only
  product observations advance the counter. Every other interaction — cart
  read, cart write, and the evaluator's snapshot — applies due mutations but
  does not advance the counter.
- A mutation (`price` and/or `stock` for one product, `after_observations: N`)
  is applied **lazily but irreversibly**: exactly once, immediately before the
  first interaction that occurs once `N` product observations have accumulated.
  With the suite's `after_observations: 1`, the first product observation shows
  the stale state and every later product observation — and the scorer's
  snapshot — show the post-mutation state.
- `Store.snapshot()` (a non-API, evaluator-only view) also triggers any due
  mutation before reading, so the scoring input is always the settled final
  state.
- Scoring benefits: recomputation of candidates, ranking, and cart-consistency
  all read the post-mutation prices/stock (§3.3 step 1, step 4). Stale-belief
  carts fail on unit price; stale-belief abstentions fail on the recomputed
  candidate emptiness; stale-belief selections fail when the mutation moved the
  winner and the agent did not re-rank.

### 3.7 One-line summary of success

> A trial succeeds iff the agent's final declared output state — its chosen
> product, abstention, or clarifying question — is the **correct action for the
> final live store state**, the cart (if any) is exactly the selection at live
> prices and in stock, and the trial terminated under budget with the
> termination reason that class of correct action demands.

## 4. Budgets, deadlines, and failure terminations

The reference evaluator enforces three independent budgets (all honored or
inflicted by the same runner code a third party can re-implement):

| Budget | Enforced | Result of exceeding |
|---|---|---|
| **Tool calls ≤ M** | The budget enforcer counts *every* allowlisted tool call — in-process: `search`, `get_listing`, `add_to_cart`, `inspect_cart`; over HTTP those same operations plus any direct `GET /api/products/{id}/reviews` the harness exposes. The counter increments before the call executes, so failed calls count too. Every recorded call lands in the tool trace. | `termination_reason = max_tool_calls_exceeded`; trial fails. |
| **Wall-clock ≤ S seconds** | Cooperative: checked before and after every tool call against a monotonic deadline; the runner additionally imposes a hard process deadline that terminates a hung worker. | `termination_reason = timeout`; trial fails; `final_state = null` if the process died before snapshotting. |
| **Correct program behavior** | Worker crash, exception from the agent, or malformed output. | `termination_reason = unrecoverable_failure`; trial fails, error string recorded, `final_state = null`. |

**Production budget.** The deterministic rules baseline needs on the order of
≤ 10 tool calls on the smallest tasks and **≈ 11 on bags** (the largest
category: 9 products ⇒ one search plus one read per product, plus
re-verification before carting). Production tool budget is therefore set at
**M = 20** (the same number the test suite uses with `--max-calls 20`), with
wall clock **S = 60 s**. Budgets are declared per run in `run_metadata`
(`max_tool_calls`, `timeout_seconds`), not per task. Third parties must state
the budgets they used when comparing scores with others'; the budget is part of
protocol, part of the result.

M = 20 keeps every agent-achievable path open: the worst case in the suite is
still comfortably below 20 for an agent that behaves correctly, yet ~2× the
baseline's bags need — recovery behavior (re-observational verification of
mutated states) stays possible without the budget itself becoming the
challenge. `isolated_trial` rejects `max_calls < 1` and `seconds ≤ 0`.

## 5. Per-trial reporting: the `TrialResult` JSONL schema

The runner emits **exactly one JSON object per line** to the output file
(refuses to overwrite an existing file). Third parties integrating via HTTP
should emit the same schema. Fields (Pydantic `TrialResult` in
`src/shopping_agent/contracts.py`, `extra="forbid"`):

| Field group | Fields |
|---|---|
| Identity | `task_id`, `task_version`, `catalog_version`, `trial_number` (1-based), `agent_name`, `mode` (`"api"` or `"browser"`), `model_id`, `prompt_version` (latter two nullable — e.g. deterministic baselines). |
| Outcome | `termination_reason` (six-value set, §3.2), `is_successful` (bool, evaluator-computed), `expected_kind` (`product` / `no_valid_product` / `clarification`), `difficulty` (`easy` / `medium` / `hard`). |
| Score detail | `constraints_satisfied`, `total_constraints` (§3.1), `selected_product_ids` (agent's final claim), `cart_items` (list of `{product_id, quantity}` from the live cart), `response_text`. |
| Efficiency | `tool_calls` (int), `duration_seconds`, optional `input_tokens`, `output_tokens`, `cost_usd`. |
| Audit | `claims` (agent's factual claims), `evidence` (per-claim supports / contradicts / unknown with `source_url` and `observed_at`), `tool_trace` (full ordered call record: `sequence`, `name`, `inputs`, `observation`, `error`, `duration_seconds`), `final_state` (full store snapshot at trial end, `null` if the trial died before it), `error` (failure string when applicable), `run_metadata` (§7 reproducibility block). |

Conventions:

- `constraints_satisfied ≤ total_constraints` is enforced at parse time.
- `final_state` is the evaluator-only snapshot (products with post-mutation
  prices/stock, cart, observation count, applied mutation indices) — publish
  it, it is the provenance for every success verdict.
- `tool_trace` records `add_to_cart` and `inspect_cart` as first-class calls;
  a failed call still occupies its sequence slot.
- A trial killed by the worker-startup deadline has `tool_calls` counting
  whatever the parent received on its trace channel — possibly zero — and the
  failure `error` in place of a final state.

## 6. Aggregation — how to report a suite score

`report.summarize` produces two identical-shape blocks, `overall` and
`by_difficulty` (fixed tiers `easy` / `medium` / `hard`). Per block:

- `trials`, `successful` (counts), and **`success_rate`** — the primary score:
  mean of the binary `is_successful` over all trials in the block.
- `product_constraint_satisfaction` — mean over `product`-kind trials
  (with `total_constraints > 0`) of `constraints_satisfied /
  total_constraints`. This is the per-constraint diagnostic; it is
  deliberately **not** pooled over clarification/abstention trials, where a
  correct empty selection re-ties to 0. A suite-level variant averages the
  per-task means over the 9 product tasks; state which definition you used.
- `termination_reasons` — the distribution of §3.2 reasons as a key–value map;
  report alongside success to distinguish "wrong answer" from "hit budget."
- `median_tool_calls`, `median_duration_seconds`, `p95_duration_seconds` —
  efficiency statistics over all trials in the block.
- `unsupported_claim_rate`, `human_rating`, `model_cost_usd`, `model_tokens` —
  present, but `null` per §2.

**Suite score (paper headline number).** Report, per agent: overall
`success_rate`, the three per-difficulty success rates, and overall
`product_constraint_satisfaction`. Overall is the unweighted mean across all
45 trials (3 reps × 15 tasks); because repetitions are a reliability device,
not a task weighting, do not reweight tasks by their rep count (they are
equal here), and do not fold hard constraints into success — report the
ledger separately.

The reference CLI reports exactly these:

```
PYTHONPATH=src py -m shopping_agent.cli run --output runs.jsonl --repetitions 3 --seed 498 --max-calls 20 --timeout 60
PYTHONPATH=src py -m shopping_agent.cli report runs.jsonl
```

(`--tasks` and `--catalog` default to the suite paths; `--max-calls` defaults
to the production budget of 20; `--agent rules|claude` selects the bundled
baselines — third-party agents integrate per §8 rather than through this flag.)

## 7. Reproducibility controls

1. **Catalog pin.** Every task pins `catalog_version: "catalog-v2"`; the run's
   `catalog.json` is the executable pin, and each `TrialResult` carries the
   catalog version and task version, so runs are comparable within
   `catalog-v2` only. A task is incompatible with a newer catalog when its
   authored-loader validation fails against that catalog.
2. **Store reset.** `Store.reset(task_id)` runs before **every** trial —
   catalog restored, cart emptied, observation and mutation counters cleared.
   Evaluator reset and state endpoints live under `/internal/*` and are
   evaluator-only; agents must never call or receive them. A trial that ends
   with cart contents it never observed scores against the cart anyway — the
   scorer sees the live cart, not the agent's belief about it.
3. **Mutations are evaluator-scheduled.** The `mutations` list is per-task
   ground truth, applied once in task order under the counter of §3.6. The
   `applied_mutations` set is visible in `final_state`, together with the
   observation count; use it to audit recovery behavior: whether the agent
   made enough of its own product reads (`observations ≥ after_observations +
   1`) that it saw the post-mutation state itself, or only the scorer's
   snapshot applied the mutation.
4. **Seeded ordering.** `run_suite` shuffles task order with `random.Random(seed)`
   (`--seed 498` default) per repetition and records the full order and
   per-task position in each row's `run_metadata.task_order` and `.task_position`.
   Order interacts with nothing else once reset (control 2) isolates each
   trial; it is recorded anyway for ablation.
5. **Metadata block.** Every row's `run_metadata` includes the runner's
   `source_sha256` (hash of every `src/**/*.py` at run time), `runner_version`,
   `baseline_version`, budgets, Python version, key package versions
   (`fastapi`, `pydantic`, `httpx`), and `started_at`. Append your own
   `model_id`, `prompt_version`, and provider batching/decoding parameters
   when integrating (§8).
6. **No-secret environment.** All scoring is offline against a local mock
   store; no network, no external service, no randomness beyond the seeded
   ordering. Determinism: two runs with the same seed and same code hash
   share the same task order and budget regime (model-side sampling is the
   only nondeterminism source when the agent is an LLM).

## 8. How to plug in your agent

The scored surface is small and implementation-independent. Either option is
scored identically; the scorer never imports your agent.

**Option A — in-process (Python).** Implement the two protocols in
`src/shopping_agent/interfaces.py`:

- `Agent.run(inputs: AgentInput, tools: ShoppingTools) → AgentOutput`, where
  `AgentInput = (request, ranking_rule)` and `AgentOutput` carries
  `selected_product_ids`, `response_text`, optional `claims`, and a
  `termination_reason` from the six-value set. Read the request, call the
  tools, decide. Your code must not import task definitions, expected
  outcomes, or any evaluator module — the runner never passes them in, and
  third-party comparisons are only valid when agents stay on this surface.
- `ShoppingTools`: `search(SearchInput)`, `get_listing(product_id)`,
  `add_to_cart(CartSelection)`, `inspect_cart()`.
  Wrap them in `BudgetedTools` to inherit the §4 budgets (or enforce an
  equivalent budget yourself in your agent, but the scoreboard only trusts
  one number: tool calls, reported by the evaluator).

Then call `eval.runner.run_trial` / `isolated_trial` / `run_suite` (or the CLI
above) with your agent instance. `claims` and `evidence` are optional at the
current version (§2); omit them freely. The output contract is
`extra="forbid"` — unknown fields are rejected at parse time, so fit your
final output to the schema rather than relying on undocumented coercion.

**Option B — over HTTP.** Start the mock store
(`py run.py`, or the FastAPI app directly) and treat the public endpoints as
your tool surface: `GET /api/products?q=…&limit=…`,
`GET /api/products/{id}`, `GET /api/products/{id}/reviews`,
`GET /api/cart`, `POST /api/cart`. An evaluator of *your* trials must,
separately, reset state between trials (`POST /internal/reset` with the
task id) and take scoring snapshots via `GET /internal/state` (the HTTP
mirror of `Store.snapshot()`); those two routes stay off-limits to the agent,
and a harness must block them from the agent side. (`/api` responses mirror
`ProductObservation`/`CartObservation` shapes; see `mock-store/README.md`.)

**What the evaluator holds.** Ground truth — expected outcome kind, valid
product ids, clarification anchor, mutation schedule, and the constraint
interpretation — lives in `data/tasks/*.json` and `example_checks.py`. It is
validated at authoring time against the catalog and (for product tasks)
re-derived; agents never receive it (§1 step 2). The scorer is in
`eval/scoring.py` and the store; that division is the integrity guarantee: an
agent that holds only §8's surface cannot distinguish the wrong candidate
(the decoys look identical) from the right one except through honest tool
use.

## 9. Deviations and their handling

Third parties sometimes must deviate. Classify and report:

| Deviation | Protocol status |
|---|---|
| Different budget M or S | Allowed, but **not comparable by default**; report both your numbers and a confirmatory run at M = 20, S = 60. |
| Parallel trials | Allowed only with per-trial store isolation (each trial owns one process); never share one in-memory store concurrently. |
| Different termination vocabulary in your logs | Map into the six-value set before scoring; unmapped reasons must fail closed (treat as `unrecoverable_failure`). |
| Re-deriving success yourself | Not protocol. The evaluator, not the agent, owns success; if you re-implement §3, publish a divergence table against `eval/scoring.score` on at least one shared run. |
| Modifying task JSONs or catalog | Not protocol; changes make your numbers incompatible with `catalog-v2`. Propose changes as a new suite version, not in-place. |
