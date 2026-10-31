# Scraped / ingested catalog feasibility

Branch: `t3/scraped-catalog-feasibility`  
Peer: multi-store partitions (`t3/multi-store-assortments`)  
Parent densify UI: [PR #17](https://github.com/t-goel/Shopping-Agent/pull/17) (catalog ground truth stayed manual)

## Live probe (2026-10-31) — can we *reach* listings?

Earlier exploration stopped at ToS/schema and did **not** pull live retailer pages. Revisited with headed Chrome (`chrome-use --launch`). Structural notes + screenshots: [`output/samples/retailer-captures/`](samples/retailer-captures/).

| Retailer | Headed browser | Raw HTTP | Listings readable? |
|---|---|---|---|
| **REI** | **yes** (PLP + PDP) | timeout / blocked | **yes** — prices, ratings, feature chips, filters |
| **Target** | **yes** (search) | 200 but flaky category redirects | **yes** — tiles with price, stars, fulfillment ETAs, social-proof badges |
| **Walmart** | **yes** (search) | not fully tested | **yes** — dense keyword titles, was/now price, badges, shipping |
| **Amazon** | **no** — "Sorry! Something went wrong" | blocked | **no** from this harness |
| Patagonia / Backcountry | not opened in browser | JS shell / empty 202 | treat as bot-walled for simple fetch |
| Hydrogen mock.shop | n/a | 200 | demo only |

**What clutter shows up when listings *are* visible** (agent-relevant chrome to densify against):

- **REI PLP:** promo carousel (Outlet / Co-op Member / Mastercard), store pickup vs ship filters, ~15 filter facets (brand, size, GORE-TEX/DryVent, sustainability…), sort, per-tile gallery + Compare + waterproof/packable chips + rating counts.
- **REI PDP:** color swatches, size chart, qty, ship vs member reward, **$30 membership upsell**, technical specs, reviews (fit / helpful votes), Q&A.
- **Target search:** ZIP/store, Pickup / Same-day / Shipping chips, “N+ bought last month”, Clearance / New / See price in cart, shipping ETAs.
- **Walmart search:** pickup/delivery chooser, Overall pick / Best seller / Flash Deal / Clearance, was→now prices, favorites gated on sign-in, optional +$ shipping, long SEO titles.

**Implication for the benchmark:** we *can* observe REI/Target/Walmart listing surfaces in a real browser for **private realism research**, but we still should **not** dump their copy/images into the public catalog (ToS + copyright + memorization). Use the clutter inventory above to densify Goodthings chrome; keep synthetic SKUs as ground truth.

### Densify capture pack (product subset + surrounding chrome)

Built from live pages for mock-store density recreation:

- Pack: [`output/samples/retailer-captures/densify-reference-pack.json`](samples/retailer-captures/densify-reference-pack.json)
- How-to: [`output/samples/retailer-captures/densify-from-retailers.md`](samples/retailer-captures/densify-from-retailers.md)
- Products: REI Torrentshell + Rainier PDPs; Target Open Story 35L PDP; Walmart 50L Flash-Deal PDP; plus PLP/search tile grids for all three
- Each entry lists **product core fields** and **all surrounding chrome** (promos, fulfillment, financing, membership, related rails, reviews/Q&A, badges) — relevant or not

## Verdict

**Do not replace catalog-v2 with wholesale Amazon (or Target/Walmart/REI) HTML scrapes for a public GitHub benchmark.** That path fails on ToS, copyright (especially images/copy), redistribution, and LLM memorization / answer-key leakage.

**Do** keep the current synthetic / manually authored catalog as evaluator ground truth, extend it via `ingest-v1` so products can later feed multi-store assortments, and optionally use official affiliate APIs or tiny manual captures only for *private* realism prototypes — never as the published answer key.

| Source | Private prototype | Public benchmark catalog | Notes |
|---|---|---|---|
| Amazon HTML scrape | gray / no | **no** | [Conditions of Use](https://www.amazon.com/conditionsofuse) forbid robots/data mining; copyright on copy/images |
| Amazon PA-API / Creators API | gray | **no** | Principal purpose must be advertising Amazon / driving sales ([PA-API practices](https://webservices.amazon.com/paapi5/documentation/best-programming-practices.html); [Creators API](https://affiliate-program.amazon.com/creatorsapi/docs/en-us/introduction)) |
| Walmart Affiliate / scrape | gray | **no** | Affiliate use = advertise Walmart.com ([Walmart I/O](https://walmart.io/apidocs/affiliates/affiliate-marketing-api)); [ToS](https://www.walmart.com/help/article/walmart-com-terms-of-use/3b75080af40340d6bbd596f11618e170) bars harvesting |
| Target | gray | **no** | No public product catalog API; [Terms](https://www.target.com/c/terms-conditions/-/N-4sr7l) forbid automated extraction |
| REI | gray | **no** | [Terms of Use](https://www.rei.com/terms-of-use) bar unauthorized extraction; popular gear specs are memorization risks |
| Manual capture (hand-typed, no media) | allowed (narrow) | gray | Private notes OK; published text must be rewritten originals |
| Synthetic products (catalog-v2 style) | **allowed** | **allowed** | Recommended. Decoys designed, not scraped |
| Open taxonomies for *ranges* (ABO CC-BY-NC, Schema.org) | allowed (NC limits) | gray / allowed with care | Use for price/spec *distributions*, not for copying listing text into the public bench |

WebShop (Yao et al. 2022) scraped ~1.18M Amazon products for a simulator; their *code* is MIT but product-dump redistribution remains murky ([issue #61](https://github.com/princeton-nlp/WebShop/issues/61)). That is not a license we can inherit for a course benchmark others will fork.

## Recommended pipeline

```text
Open taxonomies / category ranges (optional grounding)
        │
        ▼
Author / synthesize counterfactual products (fictitious brands, decoy taxonomy)
        │
        ▼
  ingest-v1 sidecar  (stores + products+provenance + assortment)
        │
        ├─► peer projector → flat CatalogExample (compat; cheapest in-stock wins)
        └─► peer projector → multi-store (stores + products + listing_id rows)
```

1. **Public catalog:** expand synthetic SKUs per `docs/benchmark/catalog-design.md`. `provenance.method = "synthetic"`; optional `retailer_hint` only as inspiration.
2. **Private prototypes only:** affiliate APIs under a personal account for throwaway notebooks — do not commit payloads, images, or verbatim titles.
3. **Ingest swap later:** partner/official feeds drop into `ingest-v1` with `provenance.method = partner_feed|official_api`.
4. **Images:** `null` or vendored stock (Unsplash/Pexels as PR #17) — never vendor CDNs.

## Attribute mapping → `Product`

| Our field | Mapping notes |
|---|---|
| `product_id` | Mint kebab slugs; never reuse ASINs in the public bench |
| `title` / `description` | Original text; hedges must match `attributes` |
| `category` | Closed set (`jackets`, `bags`, `footwear`, …) |
| `price` / `stock` / `sponsored` | **Assortment-local** in multi-store |
| `seller` ← `seller_default` | Stable brand/merchant; **not** host `brand_seller` |
| `attributes.*` | Ground truth (`waterproof`, `size`, `color`, `capacity_liters`) |
| `reviews` | Synthetic short reviews |
| `image_url` | Stock URI or null (`format: uri` when set) |
| `provenance` | Sidecar-only; stripped before `Product` (`extra=forbid`) |
| `canonical_store_id` | **Required for flat compat** — which assortment row supplies price/stock/sponsored when collapsing to one Product |

## Locked ingest ↔ multi-store alignment

| Decision | Lock |
|---|---|
| `store_id` | `trailworks-direct`, `metrowear`, `clearance-corner`, `summit-outfitters`, `headwater-supply` |
| Assortment | `(store_id, product_id) → {price, stock, sponsored}`, `listing_id = "{store_id}:{product_id}"` |
| Overlap / unique | same `product_id` in ≥2 rows vs exactly one |
| `seller` | `seller_default` → `Product.seller` |
| `brand_seller` | storefront chrome only |
| Observations | expose `store_id` alongside `product.seller` |
| Compat projection (peer) | **`canonical_store_id` required** (cheapest-in-stock fallback dropped) |
| Multi projection (peer) | `output/samples/project_ingest.py` → stores + products + listing_id rows |
| Task drafts (peer, unwired) | score by `valid_listing_ids` when overlap prices differ |

### Peer next steps (their side; acknowledged)

1. `stores-v1` contract sketches (store-scoped search; listing-keyed cart/mutations)  
2. Task drafts already sketched: cheapest shell → `trailworks-direct:ridge-shell`; tarn-fell price → `headwater-supply:tarn-fell`  
3. Compat mode remains for densify UI / existing NL suite; this thread's ingest artifacts stay source of truth

## Artifacts

| Path | Role |
|---|---|
| [`output/scrape-catalog-explore.md`](scrape-catalog-explore.md) | This report |
| [`output/samples/ingest-v1.schema.json`](samples/ingest-v1.schema.json) | Schema (`canonical_store_id`, `listing_id` pattern, `price` multipleOf 0.01, chrome-only `brand_seller`) |
| [`output/samples/ingest-v1.sample.json`](samples/ingest-v1.sample.json) | 6 products / expanded assortment (bootstrap extras included) |
| [`output/samples/stores-partition-v1.peer.json`](samples/stores-partition-v1.peer.json) | Snapshot of peer full catalog-v2 bootstrap |
| Peer `output/samples/project_ingest.py` | Their projector (compat + multi) |

### Sample assortment (expanded)

| product_id | stores (price) | notes |
|---|---|---|
| `ridge-shell` | trailworks $89, summit $94, **clearance $99** | genuine overlap + overpriced clearance |
| `ridge-shell-reseller` | clearance $69 | unique decoy |
| `harbor-backpack` | trailworks $64, metrowear $69 | overlap |
| `meadow-sling` | metrowear $29 sponsored | unique decoy |
| `headwater-duffel` | headwater $149 | unique |
| `tarn-fell` | trailworks $91, headwater $88 | overlap; `seller_default` = River Gear |

## Bottom line

Scraping retailers for maximum realism is **technically easy and legally/evaluatively bad** for a reusable benchmark. Maximum *useful* realism is synthetic catalog design + densified UI (PR #17) + multi-store partitions — with `ingest-v1` ready if a clean licensed feed ever appears.

**Peer sync complete (2026-10-30).** Ingest-v1 artifacts on `t3/scraped-catalog-feasibility` are source of truth; multi-store implements `stores-v1` independently.
