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

Concrete JSON: [`mock-store/server/examples/stores-partition-v1.json`](../../mock-store/server/examples/stores-partition-v1.json).

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

Scrape/ingest report (source of truth on their branch): `t3/scraped-catalog-feasibility` → `output/scrape-catalog-explore.md` (local agent scratch; gitignored)

| Item | Status |
|---|---|
| Five `store_id`s | locked both sides |
| Assortment / `listing_id` | locked; summit `ridge-shell` stock **3** |
| Sample overlaps | ridge-shell / harbor / tarn-fell (+ clearance genuine shell) |
| `brand_seller` | chrome-only |
| `canonical_store_id` | **required** on ingest products; flat compat uses it only |
| Public catalog source | **synthetic + ingest-v1** — no wholesale retailer scrape |
| Cross-thread traffic | done unless a contract conflict appears |

Shipped runtime (not under `output/`):

| Piece | Path |
|---|---|
| Ingest example | `mock-store/server/examples/ingest-v1.example.json` |
| Full bootstrap partition | `mock-store/server/examples/stores-partition-v1.json` |
| Loader / projection | `src/shopping_agent/ingest.py` |
| Multi-store runtime | `mock-store/server/multi_store.py` |
| Pilot tasks | `data/tasks/stores/*.json` |
| Contract sketch | `docs/benchmark/stores-v1-contracts.md` |

Expanded peer sample (6 products / 10 listings): overlaps `ridge-shell`, `harbor-backpack`, `tarn-fell`. Clearance shows genuine shell $99 beside reseller; Headwater `tarn-fell` $88 beats Trailworks $91.

**Compat rule:** use `canonical_store_id` for flat export (catalog-v2-stable), not cheapest-in-stock.

## Per-store densify chrome (from scrape peer captures)

Peer pack (not committed here; lives on `t3/scraped-catalog-feasibility` under gitignored `output/`):  
`output/samples/retailer-captures/densify-reference-pack.json` + `densify-from-retailers.md`.

Still **synthetic catalog ground truth** — captures are chrome inspiration only (no retailer CDN media in-repo).

| Our `store_id` | Clutter style | Inspiration |
|---|---|---|
| `trailworks-direct` | membership, tech filters, staff pick, specs table | REI-like |
| `summit-outfitters` | same outdoor density, premium bias | REI-like |
| `metrowear` | fulfillment chips, Circle/financing, bought-last-month | Target-like |
| `clearance-corner` | was/now, Flash Deal, keyword titles, noisy bullets | Walmart-like |
| `headwater-supply` | expedition/specialty; lean REI-like specs | REI-like (narrower) |

When multi-store UI densifies after PR #17, aim ~10–15 chrome blocks beyond title/price/ATC per PDP, using the pack’s `mock_store_densify_checklist`.

## Next steps

1. ~~Peer sync + design lock~~
2. ~~stores-v1 runtime + listing-aware scoring~~ — default NL suite still loads catalog-v2 only
3. Optional: runner CLI flag for `--catalog stores-v1`
4. Densified **per-store** UI chrome after PR #17, using the retailer capture pack as density reference
5. Keep generated scratch under `output/` (gitignored)


## Design stress findings

Stress-tested during exploration; resolutions landed as **stores-v1** on PR #19 (compat export still optional for the default NL suite).

### 1. Compat-mode projection pitfalls — resolved
- Overlap SKUs cannot collapse into one scalar `Product` without picking a store; synthetic IDs break `unique_ids` / catalog-v2 tasks.
- **Shipped:** `project_compat()` pins `canonical_store_id` price/stock/sponsored and ignores secondary assortment rows. `project_multi()` keeps listings.

### 2. Cart identity for scoring — resolved
- Product-only cart/scoring would pass Summit `$94` ridge-shell on a Trailworks `$89` lowest-price task.
- **Shipped:** Multi-store cart keys by `listing_id`; `CartSelection` / `ExpectedOutcome.valid_listing_ids`; listing-aware `score()` when snapshot has `listings`.

### 3. Mutation targeting — resolved
- Product-scoped mutations would broadcast across every store stocking a SKU.
- **Shipped:** optional `Mutation.listing_id` / `store_id` via `resolve_mutation_rows()`; unset still product-broadcast for legacy tasks.

### 4. SearchInput store scoping — resolved (stores-v1 path)
- Federated search would erase storefront discovery.
- **Shipped:** optional `SearchInput.store_id`; multi-store `/api/products` **requires** it (400 if missing); `list_stores()` tool; single-store ignores `store_id`.

### 5. Sibling ingest schema — no conflict
- Peer `brand_seller` is chrome-only; `seller_default` → `Product.seller`.
- **Shipped:** partition loader accepts `notes`/`blurb` and informational `role`.

### 6. Prototype steps — done on stores-v1
1. ~~Catalog loader projection~~ — `shopping_agent/ingest.py` (`load_ingest`, `load_partition`, `merge_partition_with_catalog`, `project_compat` / `project_multi`)
2. ~~Contract extensions~~ — listing/store fields on cart, mutation, search, observations (`docs/benchmark/stores-v1-contracts.md`)
3. ~~Listing-aware cart & mutations~~ — `mock-store/server/multi_store.py` (product-only cart rejected)
4. ~~Store-scoped search + `list_stores`~~ — `/api/stores`, `/api/stores/{store_id}/products`, shared `/api/products?store_id=`
5. ~~Pilot tasks~~ — `data/tasks/stores/multistore_cheapest_waterproof_shell.json` (+ tarn-fell price task)
