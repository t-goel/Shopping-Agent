# Catalog design — `catalog-v2`

This document explains how the mock-store catalog used by the benchmark benchmark is designed: the authoring principles, the deliberate decoy types, the attribute schema, and how the catalog supports the planned evaluation axes. It is about the benchmark data, not about any agent implementation; agents are never given this file, and none of the ground truth below is exposed through the store's public surface.

## Scope and versioning

- The catalog lives at `mock-store/server/examples/catalog.json` and is versioned by its top-level `version` field (`catalog-v2`).
- Every task definition in `data/tasks/*.json` declares a `catalog_version` that must match; the authoring loader rejects mismatches.
- Changes to existing products' ground truth (price, stock, attributes, reviews) require a new catalog version and a re-validation of every task's expected outcome. Adding products, however, is safe for tasks that constrain on `category`, as long as it does not change which existing products win.

`catalog-v2` is a pure expansion of `catalog-v1`: the six `catalog-v1` products are retained verbatim (IDs, prices, stock, reviews, order), and fourteen products were added in the new `bags` and `footwear` categories — 20 products across three categories total.

### Why the existing jacket tasks keep their expected outcomes

The five pilot tasks all constrain on `category = "jackets"`. Because no new product was placed in the `jackets` category, the valid sets and winners are unchanged:

| Task | Expected outcome | Why it still holds |
|---|---|---|
| `cheapest_waterproof_jacket` | `ridge-shell` | Cheapest waterproof size-M jacket ≤ $100; all new products are non-jackets. |
| `clarify_jacket_size` | clarification | Outcome does not depend on catalog contents. |
| `no_waterproof_under_50` | `no_valid_product` | Cheapest waterproof jacket remains $79 (`river-shell`, plus it is size S); nothing under $50 is waterproof. |
| `price_change` | `no_valid_product` | After the mutation, no waterproof size-M jacket is ≤ $100. |
| `stock_change` | `no_valid_product` | `river-shell` is the only size-S waterproof jacket and is still the sole mutation target with stock 0. |

A deliberate side constraint: the deterministic baseline re-reads every search result before ranking, so its per-task tool budget scales with the size of the `jackets` result list. Keeping that list at five products keeps the pilot's measured tool-call costs stable and comparable across catalog versions.

## Product design principles

1. **Every product has a reason to exist.** Each product either (a) is a plausibly winning answer for at least one planned task, or (b) is a named decoy/near-miss designed to be chosen by a specific failure mode. Nothing is filler.
2. **Ground truth is unauditable from the title.** The `title` is written the way a merchant writes it; the `attributes` dict is the only authoritative object. A title may say "Waterproof … Deal" while `attributes.waterproof` is `false`; the description is allowed to quietly hedge or plainly state the downside.
3. **Extreme values stay plausible.** Prices span $29–$154, stocks 0–12, ratings end-to-end. Out-of-stock items still appear in search (like real stores), and 5-star single-review items exist next to 3-star multi-review items.
4. **Near-misses fail exactly one hard constraint.** For each planned hard-constraint axis (category, waterproof, size, capacity, price cap, availability) there is at least one otherwise-perfect product that fails only that constraint. An agent that relaxes silently, filters loosely, or trusts a keyword match is directly exposed.
5. **Ranking rules have real tension.** `lowest_price`, `highest_rating`, and no-ranking tasks each produce different winners over overlapping candidate sets, and there are deliberate rating ties (broken only by product ID) so tie handling is observable.
6. **Sellers are stable brands with noisy merchandisers.** Sellers reappear across categories ("Trailworks", "Metrowear", "Summit Outfitters", "River Gear", "Clearance Corner", "Umbra Goods") so that seller credibility can be learned within a session, while "Clearance Corner" items are consistently the risky copies.

## Attribute schema

Structured `attributes` are the constraint substrate. Keys currently in use:

| Attribute | Type | Categories | Notes |
|---|---|---|---|
| `waterproof` | bool | jackets, bags, footwear | The load-bearing decoy axis. `true` only when the spec genuinely claims a waterproof construction; every "water-resistant / water-repellent / splash-proof" product is `false`, and its description says so. |
| `size` | str | jackets, footwear | Jacket sizes (`S`, `M`) and US footwear sizes (`"9"`, `"10"`, `"10.5"`). String-typed on purpose: numeric comparison of a stringed size must fail, not coerce. |
| `capacity_liters` | int | bags | Supports `gte`/`lte` capacity constraints and capacity-vs-price tradeoffs. |
| `color` | str | jackets, bags, footwear | Mostly cosmetic; useful for preference-vs-constraint mixing. |

Top-level product fields (`price`, `stock`, `category`, `sponsored`, `reviews`) are also valid constraint targets and mutation targets. Constraints may only reference fields that exist somewhere in the catalog or on the product schema; the authoring loader rejects unknown attribute names. A missing attribute yields a deterministic non-match (never a crash or a guess).

## Decoy taxonomy

Each type below has at least one concrete instance per category where it applies. Titles are quoted; `attributes` are ground truth.

| Decoy type | Instance(s) | Trap for the agent |
|---|---|---|
| **Sponsored placement** | `city-windbreaker` (jackets, $49, sponsored), `meadow-sling` (bags, $29, sponsored), `peak-quest-ultra` (footwear, $74, sponsored) | Store search lists sponsored items first. Each sponsored item is cheap, well-stocked, and fails a plausible hard constraint (`waterproof: false` in all three). A "click the first hit" habit fails these tasks, as does answering "no product" too early. |
| **Keyword-stuffed non-waterproof title** | `ridge-shell-reseller` ("Rain Shell Waterproof Jacket Deal Waterproof…", `waterproof: false`), `peak-quest-ultra` ("…Waterproof Hiking Trail Running Shoe Deal…", `waterproof: false`), `meadow-sling` ("…Waterproof Everyday Bag Deal…", `waterproof: false`) | Title-word matching without attribute verification selects the wrong item. Each description quietly states the real spec; grounding in `attributes.waterproof` is the only safe filter. |
| **Water-resistant vs. waterproof family trap** | `granite-hiker-lite` (footwear, $98, water-resistant) vs. `granite-hiker` ($127, waterproof); `canyon-pack` (bags, includes a "rain cover", `waterproof: false`) | The same product family exists in two grades and the cheaper sibling is the non-waterproof one. `canyon-pack` is also the highest-rated bag (4.67), so naive review-based ranking and keyword matching agree on the wrong item. |
| **Near-miss, wrong spec** | `swale-runner` (waterproof, right price, size `10.5` only) | Fails exactly one planned hard constraint (e.g., size) while everything else is ideal. Punishes loose boolean/filter logic. |
| **Near-miss, over budget** | `frostline-boot` (footwear, $154, waterproof), `headwater-duffel` (bags, $149, waterproof 55L), `summit-shell` (jackets, $119) | Premium-quality items just outside typical budgets; agents that sort by "best product" instead of applying the price cap fail. |
| **Near-miss, availability** | `cinder-hiker` (footwear, $69, waterproof, 5★, **stock 0**) | Cheapest genuine waterproof footwear with the catalog's only 5.0 rating — but out of stock. Static availability near-miss; also the ideal base state for a stock-mutation recovery task. |
| **Duplicate-looking reseller copy** | `ridge-shell-reseller` (jackets), `ridge-pack-reseller` (bags, $42 above the original's $39) | Same wording, same look, weaker/no specs, worse reviews; the copy is *more expensive* than the original, so both keyword matching and lazy price-ranking are separately punished. |
| **Conflicting review quality** | `swale-runner` (avg 3.0: one 5, one 1), `cinder-hiker` (single 5), `umbra-messenger` (no reviews), `fogbank-moc` (no reviews) | Averages and counts diverge from "quality"; unreviewed items are neither good nor bad but must not inherit an implicit 0 in ranking. `rank`/scoring treat no reviews as worst-of, and tasks can make that the difference between two valid candidates. |
| **Rating ties** | `granite-hiker` 4.5 (2 reviews) vs. `tarn-fell` 4.5 (4 reviews); `harbor-backpack` 4.5 (2 reviews) | Equal averages force deterministic tie-breaking by product ID and expose arbitrary "human-feel" ordering. |

## How the catalog enables the planned task axes

| Planned axis (30-task suite) | Catalog support |
|---|---|
| Hard-constraint satisfaction | Cross-category hard-constraint surfaces: `waterproof`, `size`, `capacity_liters`, price caps, plus availability. Near-misses fail exactly one. |
| Ranking / comparison | `lowest_price` tasks have tight candidate sets (`harbor-backpack` vs. `basalt-carryall`; `granite-hiker` vs. `tarn-fell`); `highest_rating` tasks hit the `canyon-pack` (4.67, not waterproof), `cinder-hiker` (5.0, out of stock), and the 4.5-tie traps. |
| Factual grounding / decoy resistance | Keyword-stuffed titles, sponsored first slots, and reseller copies whose titles contradict `attributes`. Any claim like "waterproof" must be grounded in the attribute, never the title. |
| Exogenous price/stock mutations | Existing mutation targets (`ridge-shell`, `river-shell`) remain; `cinder-hiker` (stock 0) and `basalt-carryall` (stock 2, mid-price) are pre-positioned so a future task can restore `cinder-hiker` to stock or drop a price and require recovery onto (or off of) lifecycle-affected winners. |
| Clarification | Size ambiguity (footwear sizes vs. jacket sizes) and category ambiguity (sling vs. daypack) give natural clarification surfaces; the clarification task format itself is unchanged. |
| Soft vs. hard preferences | `canyon-pack` is the most comfortable, highest-rated bag (`preferences`: "comfortable") but fails the `waterproof` hard constraint; `umbra-messenger` is valid but unreviewed; preference text must never out-vote a failed hard constraint. |

## Authoring rules going forward

- New tasks must pin `catalog_version: "catalog-v2"` until a further catalog revision changes ground truth; at that point re-run `expected_products` recomputation for every task.
- The loader (`load_examples()`) re-derives each non-clarification task's expected valid set from the catalog plus its scheduled mutations and rejects any task whose declared `valid_product_ids` disagree. Expected sets are documented by hand, never copied from agent output.
- Mutations must target products whose un-mutated state makes the task interesting (a would-be winner going bad, or a near-miss becoming valid).
- Do not "fix" a decoy by making it secretly satisfy the constraint; its job is to be tempting and wrong.
