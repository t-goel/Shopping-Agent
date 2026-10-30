# Task suite — suite-v4 (10 NL scored tasks)

Companion to [`catalog-design.md`](catalog-design.md) and
[`related-work.md`](related-work.md). Machine-readable metadata:
[`task-summary.json`](task-summary.json).

## Scope

Single-merchant comparison shopping over `catalog-v2` (20 products across
`jackets`, `bags`, and `footwear`). The **scored suite is NL-only**: agents
receive `original_text` plus store tools. Typed constraints, preferences,
ranking rules, mutations, and expected outcomes stay evaluator-held and are
never planted on agent input (`clarification_needed` is never set on NL tasks).

**Difficulty mix:** 3 easy / 3 medium / 4 hard (exactly 10 tasks).

**Catalog:** every task pins `catalog_version: "catalog-v2"` and
`version: "suite-v4"` with `agent_surface: "nl"`.

A deterministic structured rules agent must refuse or fail NL-only input; rules
100% on the Surface A harness is plumbing smoke, not competence.

**Out of scope:** multi-shop checkout, live web, multi-turn dialogs, subjective
“best” without a declared ranking rule.

## Coverage axes (one pass each across the 10)

Hard constraints, soft-vs-hard preference discipline, lowest-price ranking,
highest-rating (+ review-count tie-break), claim grounding vs title decoys,
sponsored placement, scenario implication, mid-trial price mutation
(recover + abstain), mid-trial stock replenish recovery, clarification, and
abstention.

## Easy (3)

| Task id | Kind | Winner / cue | Primary trap |
|---|---|---|---|
| `nl_cheapest_waterproof_jacket_m` | product | `ridge-shell` | sponsored + reseller keyword decoys |
| `nl_cheapest_waterproof_daypack` | product | `harbor-backpack` | rain-cover / sling / expedition near-misses |
| `nl_size9_waterproof_shoe_by_rating` | product | `tarn-fell` | OOS 5★, sponsored title, rating–review tie |

## Medium (3)

| Task id | Kind | Winner / cue | Primary trap |
|---|---|---|---|
| `clarify_jacket_size_nl` | clarification | ask for size | “usually medium” tempts a guess; no planted cue |
| `no_waterproof_jacket_under_50` | no_valid | abstain | sponsored city windbreaker under $50 |
| `prefer_comfort_but_require_waterproof_pack` | product | `basalt-carryall` | comfort language must not beat hard waterproof |

## Hard (4)

| Task id | Kind | Winner / cue | Primary trap |
|---|---|---|---|
| `price_hike_recover_to_alternative` | product | `summit-shell` | ridge hikes after 1st look; recover |
| `mutation_then_empty` | no_valid | abstain after hike | contrast with recovery task |
| `restock_recover_to_cinder` | product | `cinder-hiker` | OOS item restocks cheaper; stale cart fails |
| `implied_monsoon_kit_single_sku` | product | `harbor-backpack` | monsoon scenario → waterproof attributes |

## Surface A harness

`data/tasks/harness/` keeps five original structured-input fixtures for
reset/mutation/scoring smoke tests. They are never mixed into default
`data/tasks/` competence results. Rules-baseline success on harness is
plumbing validation only.

## Evaluation notes

- Loader reads only `*.json` directly under the tasks path (does not recurse into
  `harness/` unless that path is passed explicitly).
- Default tool budget is `M=20` (`--max-calls`).
- Ranking rule `highest_rating_then_reviews` breaks average-rating ties by
  review count (used by the size-9 shoe task).
