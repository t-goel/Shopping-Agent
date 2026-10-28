# Task design — suite-v3 (Surface B, 30 tasks)

**Status:** implemented. Primary scored suite is NL-only Surface B under `data/tasks/*.json`.  
**Catalog pin:** `catalog-v2`.  
**Harness (Surface A):** five structured-input smoke fixtures under `data/tasks/harness/` — plumbing only, never shopping competence.

## Verdict

A deterministic rules pilot scoring **15/15 in ~14ms** on structured inputs is not evidence of shopping ability. It is evidence that the **agent surface leaked the answer key**.

Surface B strips `constraints`, `preferences`, `clarification_needed`, and `ranking_rule` from `AgentInput`. The evaluator still holds typed constraints, ranking rules, mutations, and expected outcomes for deterministic scoring.

## Two surfaces

| Surface | Agent sees | Purpose | How to report |
|---|---|---|---|
| **A — Plumbing / oracle** | Structured constraints + ranking rule (`data/tasks/harness/`) | Prove reset, mutations, live-state scoring, tool budgets | “Harness validation”; never as shopping competence |
| **B — Benchmark** | **Natural-language request only** + allowlisted store tools | Measure shopping agents | Primary tables; all model/browser comparisons |

## Suite-v3 (10 easy / 10 medium / 10 hard)

Full table: [`task-suite.md`](task-suite.md). Summary:

| Tier | Count | What “good” looks like |
|---|---|---|
| Easy | 10 | Explicit constraints; decoys still punish title-trust and sponsored-first habits |
| Medium | 10 | Clarification, abstention under tempting decoys, soft-vs-hard preference conflicts |
| Hard | 10 | Mid-trial price/stock mutations (recover or abstain) and scenario implication |

Medium and hard tasks are intentionally not free: soft language pushes the wrong SKU, sponsored titles look waterproof, and mutations invalidate the first apparent winner. Easy tasks stay solvable with careful attribute grounding.

### Difficulty calibration (suite-v3)

| Tier | NL style | What must *not* appear in agent-facing text |
|---|---|---|
| Easy | Explicit constraints + ranking cue | — (decoys still live in catalog titles/sponsored slots) |
| Medium | Soft preference language, missing slots, empty-set asks | Naming the decoy rejection rule (“skip rain-cover packs”, “ignore title waterproof”) |
| Hard | Scenario implication or plain shopping ask | Mutation telegraphs (“double-check price”, “confirm stock before checkout”) |

Hard mutations fire after the first observation in the harness. Agents that buy from a stale snapshot fail; the prompt does not warn them. Soft-vs-hard mediums tempt with comfort/ratings while still requiring waterproof—without spelling which catalog SKU is the trap.

## Authoring gates (all pass)

1. NL-only agent input for Surface B (`agent_surface: "nl"`).
2. Rules-without-cheat fails or is undefined on Surface B.
3. Deterministic expected outcome from catalog + mutations + ranking rule.
4. Named decoy / near-miss for at least one failure mode (except pure empty-set / clarify).
5. Loader re-derives non-clarify valid sets; hand-authored IDs must match.
6. Clarification tasks never plant `clarification_needed` on the NL surface.

## Ranking rule note

`highest_rating_then_reviews`: max average rating, then max review count, then product id. Used by `nl_size9_waterproof_shoe_by_rating` so the 4.5 / 4.5 tie between `granite-hiker` and `tarn-fell` resolves to `tarn-fell`.

## Mapping to paper claims

| Claimed dimension | Example tasks |
|---|---|
| Constraint satisfaction | easy product tasks; soft-vs-hard mediums |
| Decoy resistance | sponsored / keyword / rain-cover traps across tiers |
| Hard vs soft | `prefer_comfort_*`, `prefer_rating_but_require_waterproof_bag` |
| Clarification | `clarify_footwear_size`, `clarify_jacket_size_nl`, `clarify_bag_capacity` |
| Abstention | `no_waterproof_*`, mutation-then-empty variants |
| Mutation recovery | `price_hike_*`, `stockout_recover_*`, `restock_recover_to_cinder` |
| Mutation abstention | `mutation_then_empty`, `stockout_then_empty_*`, `comfort_pack_stockout_abstain` |
| Claim grounding | all product tasks |
| Implication | `implied_monsoon_kit_single_sku`, `implied_bike_messenger_waterproof` |

## What we will not do in v1

- Multi-store checkout or general web navigation.
- Subjective “best product” without a declared ranking/tie rule.
- Giving agents `clarification_needed` or structured constraints on Surface B.
- Counting Surface A rules 100% as a result in the main table.
