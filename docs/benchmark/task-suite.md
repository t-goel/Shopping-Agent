# Task suite design — 15 shopping-agent tasks (`task-suite-v1`)

This document specifies the benchmark's task suite: its scope, design principles,
coverage, and difficulty calibration. It concerns benchmark *data and scoring*
only; nothing here depends on a particular agent implementation, and none of the
ground truth in `data/tasks/*.json` is exposed to any agent. Companion documents:
`catalog-design.md` (why the catalog contains what it does) and
`related-work.md` (what prior benchmarks measure and omit). Machine-readable task
metadata for the paper lives in `task-summary.json`.

## Scope

**Domain.** Single-merchant comparison shopping over a small, versioned, resettable
mock storefront (`catalog-v2`: 20 products across `jackets`, `bags`, `footwear`,
with prices $29–$154, stocks 0–12, ratings 0-review to 5.0). Each task is one
shopping request expressed in natural language plus a structured, evaluator-only
interpretation: typed constraints (hard or soft), optional preferences, an
optional ranking rule, and an expected outcome computed from catalog ground truth
and scheduled mutations.

**In scope (scored dimensions).**

1. Hard-constraint satisfaction with a per-constraint pass/fail/unknown ledger,
   including near-misses that fail exactly one constraint.
2. Soft preferences and soft constraints — they may guide ranking but must never
   out-vote a failed hard constraint.
3. Ranking under declared rules (`lowest_price`, `highest_rating`), including
   rating ties and no-review products under a stated rule.
4. Factual grounding: claims about a product must match its attributes, not its
   title (keyword-stuffed and reseller listings are fixtures).
5. Resistance to sponsored-first placement.
6. Recovery from evaluator-scheduled mid-trial **price** mutations (stale
   observation handling).
7. Recovery from evaluator-scheduled mid-trial **stock** mutations, in both
   directions (winner becomes unavailable; unavailable becomes available).
8. Clarification when the request is genuinely underspecified
   (`clarification_needed` is a scored outcome).
9. Explicit abstention when nothing satisfies the constraints
   (`no_valid_product` is a scored outcome).
10. Cross-category coverage: bags and footwear alongside jackets, with
    category-specific attributes (`capacity_liters` for bags, US shoe sizes for
    footwear).

**Out of scope (deliberately).**

- Multi-shop comparison, checkout/payment flows, shipping choices, returns,
  coupons, order management. The store's API surface is search, listing, reviews,
  cart, and evaluator-only reset/state (see `mock-store/README.md`).
- Long-horizon or multi-conversation tasks; each task is one sequential trial
  with a tool-call and wall-clock budget.
- Live-web evaluation. This is an offline, closed-world, reproducible suite; we
  view live-web suites (DeepShop, ShoppingComp) as complementary.
- Scale. 15 tasks prioritize dimension coverage and adversarial precision over
  volume; per-constraint metrics, not task count, are the contribution.

## Framework lineage

This is a **new suite**, not a variant of an existing benchmark. Its shape is
informed by prior work, without reusing their data, environments, or scoring:

- **WebShop** (Yao et al., 2022): the natural-language-instruction-plus-catalog
  task format, and the demonstration that attribute-level reward over a mock
  store is meaningful. WebShop folds all requirements into a match-style reward;
  we replace that with a typed constraint ledger, deterministic ranking rules,
  abstention outcomes, and scheduled mutations.
- **WebArena** (Zhou et al., 2024): the principle that scoring should inspect the
  *final functional state* of a stateful environment (our scorer reads the
  evaluator-only store snapshot: live prices, stock, and cart), never
  agent-reported success.
- **τ-bench** (Yao et al., 2024): scoring conversation agents against an
  annotated goal state, and clarification as a first-class behavior; our
  mutations differ in being evaluator-scheduled and adversarial rather than
  agent-driven toward a known goal.
- **WebMall** (Peeters et al., 2025): offline multi-shop reproducibility and the
  demonstration that "cheapest product" comparison is a hard task category; our
  suite stays single-shop but scores the ranking rule itself, with tie and
  no-review semantics declared in the task text.
- **DeepShop** (Lyu et al., 2026): the easy/medium/hard grading convention and
  fine-grained filter/sorting-compliance evaluation, which our ledger makes
  deterministic rather than judged.

None of the surveyed benchmarks ships: a hard/soft constraint ledger, claim
auditing over justifications, scheduled inventory mutations, scored abstention,
or engineered decoys. Those axes are what this suite operationalizes.

## Suite overview

All 15 tasks pin `catalog_version: "catalog-v2"`. The five pilot tasks keep their
original expected outcomes unchanged (no product in the `jackets` category was
added or altered in `catalog-v2`, and the pilot mutation targets are untouched).

| Task id | Difficulty | Primary axis | Expected kind | Category | Ranking | Mutations |
|---|---|---|---|---|---|---|
| `cheapest_waterproof_jacket` | easy | hard constraints + lowest price | product | jackets | lowest_price | 0 |
| `clarify_jacket_size` | medium | clarification | clarification | jackets | none | 0 |
| `no_waterproof_under_50` | medium | abstention | no_valid_product | jackets | none | 0 |
| `price_change` | hard | price mutation → abstain | no_valid_product | jackets | lowest_price | 1 |
| `stock_change` | hard | stock mutation → abstain | no_valid_product | jackets | lowest_price | 1 |
| `cheapest_waterproof_bag` | easy | hard constraints (capacity) | product | bags | lowest_price | 0 |
| `clarify_shoe_size` | easy | clarification (footwear) | clarification | footwear | none | 0 |
| `highest_rated_waterproof_shoe` | medium | rating tie + out-of-stock top item | product | footwear | highest_rating | 0 |
| `comfy_waterproof_bag` | medium | soft preference vs. hard constraint | product | bags | lowest_price | 0 |
| `jacket_title_trap` | medium | keyword-stuffed title decoy | product | jackets | lowest_price | 0 |
| `sponsored_shoe_search` | medium | sponsored-first decoy | product | footwear | lowest_price | 0 |
| `no_big_waterproof_bag` | medium | abstention (capacity near-miss) | no_valid_product | bags | none | 0 |
| `top_rated_waterproof_bag` | medium | no-review rule under declared ranking | product | bags | highest_rating | 0 |
| `duffel_price_drop` | hard | price mutation → new winner | product | bags | lowest_price | 1 |
| `stock_replenished_shoe` | hard | stock mutation → dead item revives | product | footwear | lowest_price | 1 |

Difficulty distribution: **3 easy / 8 medium / 4 hard**. Axis coverage: every
scored dimension above has at least one dedicated task, and no task exercises
only one dimension. Category coverage: 6 jackets (pilot), 5 bags, 4 footwear
tasks; the three tasks of the `jackets`-only pilot era were deliberately not
extended into more jacket variants.

## Representative task walkthroughs

### `comfy_waterproof_bag` (medium) — soft preference must not out-vote a hard constraint

- **Input.** "I want a comfortable waterproof bag for under $80. It would be nice
  to have room for at least 20 liters, and comfort matters to me, but it
  absolutely has to be genuinely waterproof." Structured form: hard constraints
  `category = bags`, `waterproof = true`, `price ≤ 80`; a *soft* constraint
  `capacity_liters ≥ 20` (`hard: false`); preference text "comfortable";
  ranking `lowest_price`.
- **Expected behavior.** The agent must reject `canyon-pack` ($58, capacity 30 L,
  highest average rating of any bag at 4.67, described as "most comfortable") even
  though it satisfies *every* soft signal and is the cheapest bag in the store,
  because its `waterproof` attribute is `false` — the description's "rain cover
  included" and one review ("Cover alone leaked in a real downpour") encode the
  water-resistant-vs-waterproof distinction. Valid hard-constraint products are
  `harbor-backpack` ($64, 22 L) and `umbra-messenger` ($71, 15 L); the
  `lowest_price` rule selects `harbor-backpack`, which also happens to satisfy
  the soft capacity threshold.
- **Success criteria.** Selected and carted exactly `harbor-backpack`; the
  per-constraint ledger records `waterproof = pass` for the selection; no
  selected product fails any hard constraint.
- **Why it is hard.** Every lazy heuristic converges on the wrong item: cheapest
  bag → `canyon-pack`; most comfortable/highest-rated → `canyon-pack`; satisfies
  the spoken preference and soft capacity → `canyon-pack`. Only treating
  `waterproof` as non-negotiable, grounded in the attribute rather than the
  title or review sentiment, yields the right answer.

### `duffel_price_drop` (hard) — mid-trial price mutation recovery

- **Input.** "Find the cheapest waterproof bag with at least 25 liters of
  capacity for at most $150. Prices at this store change without warning, so
  compare current prices before you decide." Hard constraints: `category = bags`,
  `waterproof = true`, `capacity_liters ≥ 25`, `price ≤ 150`; ranking
  `lowest_price`. Scheduled mutation: after the agent's first observation,
  `headwater-duffel`'s price changes $149 → $92.
- **Expected behavior.** From the first search, the valid set is
  {`basalt-carryall` $96, `headwater-duffel` $149} and the cheapest is
  `basalt-carryall`. Any agent that ranks from search results alone, or that
  re-checks only its chosen candidate, commits to the stale winner. Because the
  store applies the mutation before the agent's *next* read, an agent that
  re-observes listings — as a careful agent would before ranking or buying —
  sees `headwater-duffel` at $92 and must re-rank, selecting `headwater-duffel`.
- **Success criteria.** Selected and carted exactly `headwater-duffel` at its
  post-mutation price; the scorer validates the cart's unit price against live
  store state, so a cart placed on the stale $149 belief still fails.
- **Why it is hard.** The mutation is invisible unless the agent re-reads; the
  stale winner (`basalt-carryall`) remains fully valid, so eligibility alone
  never flags the problem; and `canyon-pack` (30 L, $58) is the tempting
  non-waterproof filter failure. It inverts the pilot's `price_change` task:
  there the mutation kills the only valid product (correct answer: abstain);
  here it silently installs a new winner (correct answer: switch).

### `top_rated_waterproof_bag` (medium) — ranking under a declared rule with a no-review trap

- **Input.** "Among waterproof bags with at least 20 liters of capacity, find the
  one with the highest average review rating. Treat a bag with no reviews as
  having the worst possible rating." Hard constraints: `category = bags`,
  `waterproof = true`, `capacity_liters ≥ 20`; ranking `highest_rating`.
- **Expected behavior.** Valid candidates: `harbor-backpack` (avg 4.5, 2
  reviews), `basalt-carryall` (4.0), `headwater-duffel` (5.0, single review).
  `umbra-messenger` (15 L) fails the capacity constraint; `umbra-messenger`'s
  absence is unambiguous, but the two traps are not: `canyon-pack` (4.67) would
  win if the agent ignores the waterproof attribute, and `umbra-messenger` would
  look like a reasonable "waterproof bag" pick if the agent mishandles its
  missing reviews — under the declared rule it is *worst*, not "unknown" or
  "excluded".
- **Success criteria.** Selected and carted exactly `headwater-duffel`; the
  answer must reflect the average-of-reviews rule (a single 5-star review beats a
  two-review 4.5) rather than review count or seller reputation.
- **Why it is hard.** The ranking rule must be read from the request and applied
  literally: no reviews is a defined rank, not a soft spot; and the highest
  average among *all* bags (`canyon-pack`, 4.67) belongs to a product that fails
  a hard constraint — the same soft-over-hard confusion the suite probes
  elsewhere, now inside a ranking task. The sibling task
  `highest_rated_waterproof_shoe` covers the complementary trap: an exact rating
  tie (both 4.5) means two acceptable answers, plus a 5.0-rated item that must be
  excluded for being out of stock.

## Design principles

1. **Expected outcomes are evaluator-owned and recomputed, never asserted.** For
   every non-clarification task, the authoring loader re-derives the valid set
   from the catalog plus the task's scheduled mutations
   (`example_checks.expected_products`) and rejects the task file if the
   declared `valid_product_ids` disagree. Clarification tasks are validated by
   agreement between `clarification_needed` and the expected question anchor.
2. **Agents never see ground truth.** The agent-facing surface is the request
   text, the ranking rule, and store reads. Expected outcomes, mutation
   schedules, and the constraint interpretation are withheld
   (`AgentInput` carries only `request` and `ranking_rule`; the store's
   `/internal/*` endpoints are evaluator-only).
3. **Every decoy has a nameable failure mode** (from `catalog-design.md`):
   sponsored items fail a plausible hard constraint; keyword-stuffed titles
   contradict `attributes`; near-misses fail exactly one hard constraint; the
   highest-rated item in a category may be non-waterproof or out of stock;
   unreviewed products are ranked by a rule stated in the task text, never by
   convention the agent must guess.
4. **Ranking rules have real tension.** Overlapping candidate sets produce
   different winners under different rules (footwear size-9 waterproof:
   `highest_rating` → the `granite-hiker`/`tarn-fell` tie;
   `lowest_price` → `tarn-fell`), and one task (`highest_rated_waterproof_shoe`)
   declares ties acceptable so either member of the tie is a correct answer.
5. **Mutations are only scheduled when they change the verdict.** All four
   mutation tasks change the correct final action (abstain in `price_change`/
   `stock_change`; switch winner in `duffel_price_drop`; revive a dead candidate
   in `stock_replenished_shoe`). Mutation timing (`after_observations: 1`)
   guarantees the first read shows the stale state and every later read shows
   the live state, so an agent that re-verifies at least once before deciding
   can always recover.
6. **Requests are self-contained and fair.** Nothing requires insider
   knowledge: every rule an agent must apply (tie handling, no-review ranking,
   "check prices/stock before deciding") is stated in the natural-language
   request, and every attribute an agent must respect is observable through the
   public API. Any tool-calling or browser-operating agent can be scored on the
   same terms.

## Diversity and coverage

- **Categories:** jackets (6 tasks), bags (5), footwear (4) — no category exceeds
  the pilot's jacket share, and both new categories carry attribute-specific
  reasoning (`capacity_liters` ranges, string-typed US shoe sizes that must not
  be compared numerically, e.g. `"10"` vs `"10.5"`).
- **Outcome kinds:** 11 product tasks, 3 `no_valid_product`, 2 clarification —
  no outcome kind is a rare corner.
- **Ranking rules:** 9 `lowest_price`, 2 `highest_rating`, 4 `none`; winners are
  spread across 6 distinct products (`ridge-shell`, `harbor-backpack`,
  `tarn-fell`, `headwater-duffel`, `granite-hiker`, `cinder-hiker`), so no
  product is a universal answer and no task is solved by remembering another.
- **Mutation direction:** two tasks where the mutation invalidates everything
  (abstain), two where it changes or creates the winner (recover and select).
- **Difficulty within an axis:** e.g. abstention appears easy-free (pilot),
  capacity-near-miss (`no_big_waterproof_bag`), and mutation-driven
  (`price_change`); ranking appears unconstrained-tie, no-review-rule, and
  sponsored-adjacent forms.

## Difficulty calibration method

Ratings are assigned by analysis, not by running a particular agent — but they
were sanity-checked against the deterministic rules baseline (a structured
re-verify-and-rank agent) to confirm achievability and that difficulty tracks
required behavior, not baseline quirks:

- **Easy** — a correct answer follows from a single careful pass: search the
  category, filter on grounded attributes, apply one ranking rule
  (`cheapest_waterproof_jacket`, `cheapest_waterproof_bag`), or the correct
  behavior is a single clarifying question (`clarify_shoe_size`). The rules
  baseline solves these with ≤ 8 tool calls and no recovery behavior.
- **Medium** — requires at least one non-trivial discrimination beyond obvious
  filtering: applying a *declared* ranking rule against a no-review or
  out-of-stock case, resisting the store's default ordering (sponsored first) or
  a keyword-matched title, holding a soft preference subordinate to a hard
  constraint, or correctly outputting abstention against a single-constraint
  near-miss. The baseline solves these, but each pairs the baseline's routine
  flow with at least one fixture designed against a common heuristic.
- **Hard** — correct behavior requires reacting to information that is not
  available on the first observation (mid-trial mutations) and changing course
  accordingly: re-verifying before committing, re-ranking after a price change,
  re-checking availability of an item that appeared dead, or abandoning a task
  one had nearly completed (`price_change`, `stock_change`,
  `duffel_price_drop`, `stock_replenished_shoe`).

Distribution: 3 easy / 8 medium / 4 hard. The suite is medium-weight by design:
easy tasks anchor the scale and detect gross failures; medium tasks carry the
decoy and declared-rule axes; hard tasks isolate dynamic-state behavior where
single-snapshot agents should measurably separate.

## How to evaluate your own agent

1. Implement the agent-facing surface (`src/shopping_agent/interfaces.py`):
   receive `AgentInput` (request text, structured constraints/preferences as
   parsed by your own layer, and the ranking rule), act through `ShoppingTools`
   (search, get_listing, add_to_cart, inspect_cart), return an `AgentOutput`
   with selected product IDs, free-text response, claims, and a termination
   reason from the fixed set.
2. Reset store state per trial (`Store.reset(task_id)`); run each task
   sequentially with a tool-call and wall-clock budget you declare in the run
   metadata.
3. Score only through the evaluator path (`eval.scoring.score` against the
   store snapshot), which checks the constraint ledger, ranking validity, cart
   contents, live price/stock consistency, and the claim-evidence audit.
   Budget guidance: the deterministic baseline needs ≤ 8 calls on jackets, 10 on
   footwear, and 11 on bags tasks (bags is the largest category, at 9 products);
   a budget of ~15–20 calls keeps recovery behavior possible without making the
   budget itself the challenge.

## Known risks and limitations

- **Ground truth is authored.** Expected outcomes are hand-derived and
  loader-validated against the catalog, not observed from real user behavior.
- **Closed world.** Decoy resistance is measured against this suite's fixture
  taxonomy; the taxonomy is documented so future catalog versions can vary it.
- **Clarification is scripted.** The scored signal is whether the agent asks a
  question containing the expected anchor ("size"), not a full user simulation.
- **Baseline budget coupling.** The deterministic baseline's tool budget scales
  with category size; tasks are validated with an explicit budget in the test
  suite, and the eval-protocol layer owns the production budget choice.
