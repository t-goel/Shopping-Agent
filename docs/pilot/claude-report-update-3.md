# Evaluation evidence

| Task | Successful / trials | Median calls | Median seconds | p95 seconds |
|---|---:|---:|---:|---:|
| clarify_jacket_size_nl | 0/3 | 2 | 9.2500 | 9.5620 |
| implied_monsoon_kit_single_sku | 1/3 | 11 | 15.9210 | 18.2500 |
| mutation_then_empty | 0/3 | 2 | 8.3910 | 8.7340 |
| nl_cheapest_waterproof_daypack | 0/3 | 7 | 19.6400 | 19.8750 |
| nl_cheapest_waterproof_jacket_m | 0/3 | 2 | 8.7650 | 9.2810 |
| nl_size9_waterproof_shoe_by_rating | 0/3 | 5 | 9.7820 | 9.9210 |
| no_waterproof_jacket_under_50 | 0/3 | 3 | 11.6400 | 12.5160 |
| prefer_comfort_but_require_waterproof_pack | 0/3 | 10 | 19.1100 | 23.7350 |
| price_hike_recover_to_alternative | 0/3 | 2 | 9.8280 | 10.4070 |
| restock_recover_to_cinder | 0/3 | 5 | 13.5470 | 15.6720 |

## Failures

- nl_cheapest_waterproof_jacket_m, repetition 1: unrecoverable_failure; termination=unrecoverable_failure; selected=[].
- price_hike_recover_to_alternative, repetition 1: unrecoverable_failure; termination=unrecoverable_failure; selected=[].
- nl_size9_waterproof_shoe_by_rating, repetition 1: incorrect_abstention; termination=no_valid_product; selected=[].
- clarify_jacket_size_nl, repetition 1: unrecoverable_failure; termination=unrecoverable_failure; selected=[].
- restock_recover_to_cinder, repetition 1: unrecoverable_failure; termination=unrecoverable_failure; selected=[].
- mutation_then_empty, repetition 1: unrecoverable_failure; termination=unrecoverable_failure; selected=[].
- implied_monsoon_kit_single_sku, repetition 1: unrecoverable_failure; termination=unrecoverable_failure; selected=[].
- nl_cheapest_waterproof_daypack, repetition 1: unrecoverable_failure; termination=unrecoverable_failure; selected=[].
- no_waterproof_jacket_under_50, repetition 1: unrecoverable_failure; termination=unrecoverable_failure; selected=[].
- prefer_comfort_but_require_waterproof_pack, repetition 1: unrecoverable_failure; termination=unrecoverable_failure; selected=[].
- clarify_jacket_size_nl, repetition 2: unrecoverable_failure; termination=unrecoverable_failure; selected=[].
- prefer_comfort_but_require_waterproof_pack, repetition 2: unrecoverable_failure; termination=unrecoverable_failure; selected=[].
- implied_monsoon_kit_single_sku, repetition 2: hard_constraint_violation; termination=completed; selected=['basalt-carryall'].
- nl_cheapest_waterproof_daypack, repetition 2: unrecoverable_failure; termination=unrecoverable_failure; selected=[].
- no_waterproof_jacket_under_50, repetition 2: unrecoverable_failure; termination=unrecoverable_failure; selected=[].
- price_hike_recover_to_alternative, repetition 2: unrecoverable_failure; termination=unrecoverable_failure; selected=[].
- nl_size9_waterproof_shoe_by_rating, repetition 2: incorrect_abstention; termination=no_valid_product; selected=[].
- mutation_then_empty, repetition 2: unrecoverable_failure; termination=unrecoverable_failure; selected=[].
- nl_cheapest_waterproof_jacket_m, repetition 2: unrecoverable_failure; termination=unrecoverable_failure; selected=[].
- restock_recover_to_cinder, repetition 2: unrecoverable_failure; termination=unrecoverable_failure; selected=[].
- price_hike_recover_to_alternative, repetition 3: unrecoverable_failure; termination=unrecoverable_failure; selected=[].
- no_waterproof_jacket_under_50, repetition 3: unrecoverable_failure; termination=unrecoverable_failure; selected=[].
- nl_cheapest_waterproof_jacket_m, repetition 3: unrecoverable_failure; termination=unrecoverable_failure; selected=[].
- nl_cheapest_waterproof_daypack, repetition 3: unrecoverable_failure; termination=unrecoverable_failure; selected=[].
- prefer_comfort_but_require_waterproof_pack, repetition 3: unrecoverable_failure; termination=unrecoverable_failure; selected=[].
- clarify_jacket_size_nl, repetition 3: unrecoverable_failure; termination=unrecoverable_failure; selected=[].
- restock_recover_to_cinder, repetition 3: unrecoverable_failure; termination=unrecoverable_failure; selected=[].
- nl_size9_waterproof_shoe_by_rating, repetition 3: incorrect_abstention; termination=no_valid_product; selected=[].
- mutation_then_empty, repetition 3: unrecoverable_failure; termination=unrecoverable_failure; selected=[].

Categories describe observed outcomes; root causes require trace inspection.
Repeated trials are not independent tasks. API timings are not browser timings.
Missing token/cost measurements remain null; no price estimate is invented.
