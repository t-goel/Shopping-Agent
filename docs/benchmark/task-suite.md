# Task suite — suite-v3 (30 Surface B tasks)

Companion to [`task-design.md`](task-design.md) and [`catalog-design.md`](catalog-design.md).
Machine-readable metadata: [`task-summary.json`](task-summary.json).

## Scope

Single-merchant comparison shopping over `catalog-v2` (20 products). Agents on
the scored surface receive **natural-language text only** plus store tools.
Typed constraints, ranking rules, mutations, and expected outcomes are
evaluator-held.

**Difficulty:** 10 easy / 10 medium / 10 hard.

**Paper subset:** the ICLR draft centers on ten of these tasks (4 easy / 3 medium /
3 hard) mirrored under [`data/tasks/b/`](../../data/tasks/b/). Full suite stays
in [`data/tasks/`](../../data/tasks/).

**Out of scope:** multi-shop checkout, live web, multi-turn dialogs, subjective
“best” without a declared ranking rule.

## Easy (10)

| Task id | Kind | Winner / cue | Primary trap |
|---|---|---|---|
| `nl_cheapest_waterproof_jacket_m` | product | `ridge-shell` | sponsored + reseller keyword decoys |
| `nl_cheapest_waterproof_daypack` | product | `harbor-backpack` | rain-cover / sling / expedition near-misses |
| `nl_size9_waterproof_shoe_by_rating` | product | `tarn-fell` | OOS 5★, sponsored title, rating–review tie |
| `nl_cheapest_waterproof_jacket_s` | product | `river-shell` | medium jackets look cheaper/better but wrong size |
| `nl_cheapest_waterproof_shoe_size9_under_100` | product | `tarn-fell` | OOS `cinder-hiker`, sponsored non-WP |
| `nl_cheapest_waterproof_compact_bag` | product | `umbra-messenger` | daypacks and keyword sling under 15L |
| `nl_highest_rated_waterproof_jacket_m` | product | `summit-shell` | sponsored 5★ windbreaker is not waterproof |
| `nl_navy_waterproof_jacket_m` | product | `ridge-shell` | navy reseller copy is not waterproof |
| `nl_waterproof_30l_under_100` | product | `basalt-carryall` | `canyon-pack` 30L rain-cover near-miss |
| `nl_black_waterproof_jacket_m` | product | `summit-shell` | color + waterproof grounding |

## Medium (10)

| Task id | Kind | Winner / cue | Primary trap |
|---|---|---|---|
| `clarify_footwear_size` | clarification | ask for size | guessing size / sponsored shoe |
| `no_waterproof_pack_under_40` | no_valid | abstain | keyword “waterproof” sling under $40 |
| `prefer_comfort_but_require_waterproof_pack` | product | `basalt-carryall` | comfort language pulls to non-WP `canyon-pack` (NL does not name it) |
| `clarify_jacket_size_nl` | clarification | ask for size | “usually medium” tempts a guess |
| `no_waterproof_jacket_under_50` | no_valid | abstain | sponsored city windbreaker under $50 |
| `no_waterproof_shoe_size10` | no_valid | abstain | sponsored size-10 “waterproof” title decoy |
| `prefer_rating_but_require_waterproof_bag` | product | `harbor-backpack` | highest-rated overall is rain-cover `canyon-pack` |
| `clarify_bag_capacity` | clarification | ask liters/capacity | laptop vs clothes use-size left open |
| `prefer_comfort_but_require_waterproof_shoe` | product | `tarn-fell` | camp moc / mesh “deal” comfort decoys |
| `no_waterproof_expedition_under_100` | no_valid | abstain | `headwater-duffel` exists but over budget |

## Hard (10)

| Task id | Kind | Winner / cue | Primary trap |
|---|---|---|---|
| `price_hike_recover_to_alternative` | product | `summit-shell` | ridge hikes after 1st look; no re-check hint in NL |
| `stockout_recover_footwear` | product | `granite-hiker` | tarn stocks out mid-trial; must recover |
| `implied_monsoon_kit_single_sku` | product | `harbor-backpack` | monsoon scenario, not attribute dump |
| `mutation_then_empty` | no_valid | abstain after hike | contrast with recovery task |
| `restock_recover_to_cinder` | product | `cinder-hiker` | OOS item restocks cheaper; stale cart fails |
| `stockout_then_empty_footwear_budget` | no_valid | abstain after stockout | do not climb above $100 budget |
| `implied_bike_messenger_waterproof` | product | `umbra-messenger` | hydration backpack already worn → crossbody |
| `comfort_pack_stockout_abstain` | no_valid | abstain after basalt OOS | comfort trap must not buy `canyon-pack` |
| `price_hike_daypack_recover_carryall` | product | `basalt-carryall` | harbor hikes; recover within 20–30L band |
| `stockout_size_s_jacket_empty` | no_valid | abstain after river OOS | sole size-S WP jacket disappears |

## Surface A harness

`data/tasks/harness/` keeps the original five structured-input fixtures for
reset/mutation/scoring smoke tests. Rules-baseline 100% on harness is **not**
a shopping-competence result.
