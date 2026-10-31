# Densify mock stores from live retailer captures

Source pack: [`densify-reference-pack.json`](densify-reference-pack.json)  
Raw dumps + screenshots in this folder.

## What we captured (subset)

| ID | Retailer | Page | Core product signal |
|---|---|---|---|
| `rei-torrentshell` | REI | PDP | Patagonia Torrentshell 3L, $189, 4.4★ / 342 |
| `rei-rainier` | REI | PDP | REI Co-op Rainier, $99.95, 4.1★ / 454 |
| `target-openstory-35l` | Target | PDP | Open Story 35L travel pack, $50, New + 900+ bought |
| `walmart-muzpu-50l` | Walmart | PDP | 50L travel pack, $31.49 was $58.99, Flash Deal, 4.5★ / 943 |
| PLP/search snapshots | REI / Target / Walmart | listing grids | tile + filter clutter |

## How to recreate density on Goodthings (without shipping retailer media)

1. **Keep synthetic SKUs** as evaluator ground truth (`ingest-v1` / catalog-v2).
2. **Mirror chrome zones** from `mock_store_densify_checklist` in the pack JSON onto storefront PDP/PLP (PR #17 densify path).
3. **Map store roles** to clutter styles when multi-store lands:
   - `trailworks-direct` / `summit-outfitters` → REI-like (membership, tech filters, staff pick, specs table)
   - `metrowear` → Target-like (fulfillment chips, Circle/financing, bought-last-month)
   - `clearance-corner` → Walmart-like (was/now, Flash Deal, keyword-stuffed titles, AI-ish bullets)
4. **Budget of noise per PDP** (aim to match captures): ~10–15 distinct chrome blocks beyond title/price/ATC.
5. **Do not** commit retailer CDN images; keep Unsplash/Pexels or null.

## Field → mock mapping

| Live chrome | Mock field / UI |
|---|---|
| Membership / Circle / financing | decoy savings chrome (not price) |
| Pickup / ship / ETA | fulfillment chooser on PDP |
| Staff pick / Flash Deal / bought-N | badges on tile + PDP |
| Was/now | trail-mark pricing (already in densify PR) |
| Specs table | structured attributes + visible “Technical Specs” |
| Reviews + Q&A | review list + optional Q&A stubs |
| Related rails | kit bundles / similar SKUs |
| Waterproof-in-title | keyword decoys with `attributes.waterproof: false` |

## Files to open

- Pack: `densify-reference-pack.json`
- Screenshots: `*-full.png`, `*-capture.png`
- Visible text dumps: `*-text.txt` (full surrounding copy for density calibration)
