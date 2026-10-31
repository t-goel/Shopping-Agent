# Multi-store assortments — exploration

**Status: LOCKED peer sync** · **stores-v1 runtime implemented** (2026-10-30)

Branch: `t3/multi-store-assortments`  
Peer: scrape/ingest (`t3/scraped-catalog-feasibility`) — `ingest-v1` source of truth  
Parent densify UI: [PR #17](https://github.com/t-goel/Shopping-Agent/pull/17) (catalog ground truth unchanged)

## Goal

Turn the single Goodthings catalog into **3–5 storefronts** with overlapping and unique SKUs so agents must pick the right store (or search across stores) instead of querying one flat inventory. Evaluator honesty stays intact: attributes/price/stock ground truth remain authoritative; store partitions add navigation/search challenge, not answer-key leakage.

## Alignment with scrape sibling (ingest-v1)

Confirmed against their opening sketch:

| Decision | Lock |
|---|---|
| `store_id` | `kebab-case`, stable slugs |
| Product vs listing | Canonical `Product` (contracts.py, `extra=forbid`) holds identity + attributes + reviews; **assortment** rows hold per-store `price` / `stock` / `sponsored` |
| Overlap | Same `product_id` in ≥2 assortment rows |
| Unique | Exactly one assortment row |
| `listing_id` | `{store_id}:{product_id}` (deterministic) |
| Provenance | Sidecar-only; never on evaluator-facing `Product` |
| Projection | Ingest → products + assortment → today's flat `CatalogExample` *or* a future multi-store catalog |

## Five stores (bootstrap)

| `store_id` | Display name | Role | `brand_seller` |
|---|---|---|---|
| `trailworks-direct` | Trailworks Direct | Core outdoor brand shop; absorbs River Gear SKUs as co-listed specialty | `Trailworks` |
| `metrowear` | Metrowear | Lifestyle / city; owns sponsored keyword decoys | `Metrowear` |
| `clearance-corner` | Clearance Corner Outpost | Reseller copies + a few genuine overpriced overlaps | `Clearance Corner` |
| `summit-outfitters` | Summit Outfitters | Premium outdoor; price-overlap on a few Trailworks winners | `Summit Outfitters` |
| `headwater-supply` | Headwater Supply | Expedition / specialty; unique big duffels, winter, Umbra | `Headwater Supply` |

Seller strings from catalog-v2 that are **not** their own store (`River Gear`, `Umbra Goods`, `Frostline Supply`) keep their display `seller` on the product and are placed into the nearest specialty store's assortment. See `seller` rule below.

## Overlap rules

1. **Identity is global.** `product_id` is canonical. Attributes, title, description, reviews, and `seller` live on the product once. Stores never rewrite waterproof/size/capacity ground truth.
2. **Assortment is the only store-local surface.** `(store_id, product_id) → {price, stock, sponsored}`. Overlap = same product in ≥2 stores; prices may differ (±$3–$15) so lowest-price tasks force a store choice. Stock may differ so availability recovery can be store-scoped later.
3. **Decoys stay unique.** Keyword-stuffed / sponsored / reseller copies appear in exactly one store (`metrowear` or `clearance-corner`). Agents that only search Metrowear find the trap; the genuine winner lives elsewhere.
4. **Specialty uniques.** Large expedition / winter / Umbra SKUs live only on `headwater-supply` so "right store" is a real axis.
5. **Overlap budget (bootstrap).** ~4–6 overlapping SKUs across 20 catalog-v2 products; rest unique. Expand overlaps when scraped/synthetic inventory arrives.
6. **No answer-key in store names.** Store branding does not encode task solutions (e.g. no store named "Waterproof Jackets Under 100").

## `seller` vs `brand_seller`

- Keep **`seller` / `seller_default` on the product** as the merchant/brand display string used by UI and constraints today.
- Store `brand_seller` is **chrome only** (store header). It may match house-brand products, but must **not** be projected onto `Product.seller` per listing — a shared `product_id` can only have one seller string, and overwriting it with the hosting store would make `ridge-shell` look like Summit when listed there and break co-listed brands (River Gear on Trailworks, Umbra on Headwater).
- Listing observations should expose `store_id` (+ optional store name) **alongside** the product's stable `seller`.
- **Locked with scrape peer:** schema now documents chrome-only `brand_seller`; `seller_default` is required and is the only path to `Product.seller`.

## API / reset implications (sketch, not implemented yet)

Today: one `Store` instance, flat search, cart keyed by `product_id`.

Proposed additive path:

1. **Catalog file** gains optional `stores[]` + `assortment[]` (or separate `stores.json` + keep products). Loader projects to either:
   - **Compat mode:** merge assortment into one flat product list (single-store densify UI / existing NL suite keep working).
   - **Multi mode:** search requires `store_id` (or a new `list_stores` + store-scoped `search`).
2. **Cart:** either store-scoped carts or a marketplace cart that records `(store_id, product_id)`. Prefer marketplace cart with listing identity so cross-store price wins are checkable.
3. **Mutations:** target `listing_id` or `(store_id, product_id)` so a price drop on one store does not silently mutate another.
4. **Scoring:** `valid_product_ids` can stay product-level for bootstrap; later tasks may require a specific `listing_id` / store when overlap prices differ.
5. **Reset:** still one trial store process; reset reloads products + full assortment matrix.

Do **not** break the NL suite on main until multi-mode is behind an explicit catalog version (e.g. `catalog-v3` / `stores-v1`) and tasks opt in.

## Tool-surface changes (when multi-mode ships)

| Tool | Change |
|---|---|
| `list_stores()` | New; returns store_id, name, blurb |
| `search` | Add optional/required `store_id`; empty store → error or federated search (decide before tasks) |
| `get_listing` | Accept `listing_id` **or** `(store_id, product_id)`; return store_id in observation |
| `add_to_cart` | Carry store/listing identity |
| Browser | Store picker / URL path `/s/{store_id}/…` on densified UI later |

Recommendation: **require `store_id` for search** in multi-mode. Federated search collapses the navigation challenge.

## Bootstrap partition summary

Concrete JSON: [`output/samples/stores-partition-v1.json`](samples/stores-partition-v1.json).

| Store | Unique highlights | Overlap SKUs |
|---|---|---|
| `trailworks-direct` | `ridge-pack`, `river-shell`, `granite-hiker` | `ridge-shell`, `harbor-backpack`, `tarn-fell` |
| `metrowear` | sponsored decoys (`city-windbreaker`, `meadow-sling`, `peak-quest-ultra`), `fogbank-moc`, `canyon-pack` | `harbor-backpack` ($69) |
| `clearance-corner` | `ridge-shell-reseller`, `ridge-pack-reseller` | `ridge-shell` (genuine overprice $99) |
| `summit-outfitters` | `summit-shell`, `basalt-carryall`, `swale-runner` | `ridge-shell` ($94) |
| `headwater-supply` | `headwater-duffel`, `frostline-boot`, `umbra-messenger`, `cinder-hiker` | `tarn-fell` ($88) |

Overlap intent (aligned with scrape sample where noted):

- `ridge-shell`: Trailworks $89 / Summit $94 / Clearance genuine $99 — matches scrape sample on Trailworks+Summit; Clearance row is full-bootstrap only.
- `harbor-backpack`: Trailworks $64 / Metrowear $69 — **matches scrape sample** (Metrowear, not Summit).
- `tarn-fell`: Trailworks $91 / Headwater $88 — full-bootstrap only; not in the 5-SKU scrape sample yet.
- Decoys unique: reseller → Clearance; sponsored sling → Metrowear; expedition duffel → Headwater.

## Required listing / ingest fields (for scrape sibling)

Minimum for merge into our partition:

**Store**

- `store_id` (kebab-case)
- `name`
- `brand_seller`

**Product** (projects into contracts `Product`)

- `product_id`, `title`, `description`, `category`
- `currency` (`USD`)
- `seller` (display; not derived from store)
- `attributes` (bool/int/str; waterproof/size/capacity_liters/color as applicable)
- `reviews[]` (`review_id`, `rating`, `text`)
- `image_url` (nullable; stock/hotlink only — no copyrighted Amazon blobs)

**Assortment row**

- `store_id`, `product_id`
- `price`, `stock`, `sponsored`
- `listing_id` = `{store_id}:{product_id}`

**Sidecar-only (ok, stripped before evaluator Product)**

- `provenance.{method,retailer_hint,source_url,captured_at,notes}`

Optional later: `blurb`, `fulfillment`, store chrome tokens — not needed for bootstrap.

## Peer lock status (2026-10-30) — **CLOSED**

Scrape/ingest report (source of truth on their branch): `t3/scraped-catalog-feasibility` → `output/scrape-catalog-explore.md`  
Local mirror: `output/scrape-catalog-explore.peer.md`

| Item | Status |
|---|---|
| Five `store_id`s | locked both sides |
| Assortment / `listing_id` | locked; summit `ridge-shell` stock **3** |
| Sample overlaps | ridge-shell / harbor / tarn-fell (+ clearance genuine shell) |
| `brand_seller` | chrome-only |
| `canonical_store_id` | **required** on ingest products; flat compat uses it only |
| Public catalog source | **synthetic + ingest-v1** — no wholesale retailer scrape |
| Cross-thread traffic | done unless a contract conflict appears |

Prototypes under `output/samples/` (not wired into mock-store / NL suite):

| Script | Output | Behavior |
|---|---|---|
| `project_assortment.py` | `catalog-v2-stores-compat.json` | catalog-v2 + partition → flat Products |
| `project_ingest.py` | `ingest-v1.compat.json`, `ingest-v1.multi.json` | ingest-v1 → compat (via `canonical_store_id`) **or** stores+listings |
| `multi_store_search.py` | stdout demo | **requires** `store_id`; sponsored-first; seller stays `seller_default` |
| `task-multistore-*.draft.json` | — | listing_id-scored task drafts (not loaded by mock-store) |

Expanded peer sample (6 products / 10 listings) re-projected clean: overlaps `ridge-shell`, `harbor-backpack`, `tarn-fell`. Clearance shows genuine shell $99 beside reseller; Headwater `tarn-fell` $88 beats Trailworks $91.

**Compat rule (updated):** use `canonical_store_id` for flat export (catalog-v2-stable), not cheapest-in-stock — cheapest-in-stock would pull `tarn-fell` to $88 and drift tasks that expect Trailworks/canonical prices.

## Next steps

1. ~~Keep peer thread synced as partitions lock~~ — mutual lock done.
2. ~~Prototype loader projection + store-scoped search~~ — under `output/samples/`.
3. ~~Draft multi-store task shapes~~ — `task-multistore-cheapest-shell.draft.json`, `task-multistore-tarn-fell-price.draft.json`.
4. ~~Sketch listing-keyed cart + mutations contracts~~ — `output/samples/stores-v1-contracts.sketch.md`.
5. ~~Implement stores-v1 runtime~~ — `shopping_agent/ingest.py`, `mock-store/server/multi_store.py`, additive contracts, `GET /api/stores`, store-scoped search, listing-keyed cart/mutations, tasks under `data/tasks/stores/`, listing-aware scoring. Default NL suite still loads catalog-v2 only.
6. Optional next: runner CLI flag for `--catalog stores-v1`; densified multi-store UI after PR #17.


## Design stress findings

### 1. Compat-mode projection pitfalls (overlap SKUs collapsing to one Product)
- **Price / stock collision:** `Product` requires scalar `price` and `stock`, while `CatalogExample` enforces strict global `product_id` uniqueness. Overlap SKUs (`ridge-shell`, `harbor-backpack`, `tarn-fell`) have divergent prices across stores (e.g. `ridge-shell` at $89, $94, $99).
- **Evaluation corruption:** Selecting min-price or arbitrary first/last assortment row alters ground-truth budget constraints and lowest-price evaluations compared to `catalog-v2`. Summing stock creates fictitious inventory; picking a single store hides inventory. Synthesizing IDs (e.g. `ridge-shell--summit`) breaks existing tasks expecting canonical `valid_product_ids`.
- **Compat rule:** Compat-mode projection cannot dynamically reconcile multi-store offers. It must strictly pin a single designated "canonical store" (e.g. `trailworks-direct` matching `catalog-v2` baseline values) and ignore secondary store assortment rows entirely during flat export.

### 2. Cart identity: `product_id` vs `listing_id` for scoring
- **Scoring blindspot:** `CartSelection` and `ExpectedOutcome.valid_product_ids` currently key solely on `product_id`. If an agent adds `ridge-shell` from `summit-outfitters` ($94) instead of `trailworks-direct` ($89) for a lowest-price prompt, evaluating against `valid_product_ids: ["ridge-shell"]` awards an unearned pass.
- **Cart collisions:** Keying `Store.cart` by `product_id` collapses multi-store purchases into one line item with ambiguous unit pricing.
- **Resolution:** Cart items must carry `listing_id` (`{store_id}:{product_id}`). For multi-store tasks, `ExpectedOutcome` must evaluate `valid_listing_ids` (or store-qualified pairs) whenever pricing or availability differs across stores. `CartSelection` should add optional `listing_id` and `store_id` fields while retaining `product_id` for backwards compatibility.

### 3. Mutation targeting (listing-scoped)
- **Current contract:** `Mutation` only takes `product_id`, mutating global `Product.price` / `Product.stock` across all observations.
- **Store isolation failure:** A stockout or price change targeted at `product_id` either uniformly mutates all stores stocking that SKU (destroying store isolation) or only touches a privileged store. Essential scenarios—such as Trailworks stocking out mid-trial to force the agent to find stock at Summit, or Metrowear running a flash sale—cannot be modeled.
- **Resolution:** `Mutation` requires an optional `listing_id: str | None = None` (or `store_id: str | None = None`). When specified, only the designated store's assortment row mutates. Unset/null defaults to canonical store or all-store broadcast for legacy `catalog-v2` tasks.

### 4. SearchInput: `store_id` timing (now vs catalog-v3)
- **Keep SearchInput unchanged for now; add `store_id` in catalog-v3.**
- `SearchInput` enforces `extra="forbid"`. Adding optional `store_id: str | None = None` now is schema-compatible, but the `mock-store` runtime `/api/products` and `Store.search()` do not accept `store_id`, creating a dead contract surface before runtime support exists.
- Crucially, multi-mode should **require** `store_id` (store-scoped search) rather than making it optional. An optional `store_id` enables federated search across all stores, eliminating the navigation challenge of discovering and querying specific storefronts. Store-scoping belongs cleanly in the `catalog-v3` / multi-mode release.

### 5. Sibling ingest schema conflict check
- **No conflict — peer schema already aligned.**
- Sibling schema `ingest-v1.schema.json` and sample `ingest-v1.sample.json` on `t3-1f10f551` have already incorporated our rejection of `brand_seller -> Product.seller`.
- The schema explicitly documents `stores[].brand_seller` as *"Storefront chrome / branding only. Do NOT project onto Product.seller — a shared product_id keeps one stable seller (seller_default)."*
- Sibling schema defines `products[].seller_default` to project into `Product.seller`, ensuring co-listed products (e.g. River Gear on Trailworks) maintain stable identity.
- Minor differences to normalize: sibling stores schema uses `notes` whereas `stores-partition-v1.json` uses `blurb` (loader should accept both); sibling assortment does not include the bootstrap partition's informational `role` field (safe to ignore).

### 6. Concrete minimal next prototype steps
1. **Catalog loader projection:** Build an offline helper in `shopping_agent/` that parses `stores-partition-v1.json` + products, implementing both canonical-store compat projection (zero drift from `catalog-v2`) and multi-store assortment loading.
2. **Draft `catalog-v3` contracts:** Define backwards-compatible extensions with optional `listing_id` / `store_id` on `CartSelection` and `Mutation`, and a store-scoped search input contract.
3. **Listing-aware cart & mutations in mock-store:** Update `Store` state machine in a feature branch to key cart inventory and pending mutations by `listing_id` (`{store_id}:{product_id}`).
4. **Store-scoped search endpoint:** Add store routing (e.g. `/api/stores/{store_id}/products` or `list_stores()` tool) requiring `store_id` so agents cannot bypass store discovery.
5. **Pilot multi-store task:** Author a single proof-of-concept task (`task-multistore-cheapest-shell`) requiring lowest-price selection of `ridge-shell` at Trailworks ($89) over Summit ($94), scored by `listing_id`.
