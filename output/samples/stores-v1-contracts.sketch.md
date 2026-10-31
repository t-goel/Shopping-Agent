# stores-v1 contract sketch (exploration)

Additive extensions only. Do **not** change `contracts.py` until a catalog-v3 / stores-v1 cutover is scheduled. Existing NL suite stays on `catalog-v2`.

## Models

```python
# Additive fields — all optional so catalog-v2 tasks keep validating.

class StoreRecord(Contract):
    store_id: str  # kebab-case
    name: str
    brand_seller: str  # chrome only

class SearchInput(Contract):
    query: str
    max_results: int = 20
    store_id: str | None = None  # REQUIRED when catalog_version startswith "stores-"

class CartSelection(Contract):
    product_id: str
    quantity: int
    store_id: str | None = None
    listing_id: str | None = None  # preferred key when present

class Mutation(Contract):
    after_observations: int
    product_id: str
    price: float | None = None
    stock: int | None = None
    store_id: str | None = None
    listing_id: str | None = None  # mutates one assortment row only

class ExpectedOutcome(Contract):
    kind: Literal["product", "no_valid_product", "clarification"]
    valid_product_ids: list[str] = []
    valid_listing_ids: list[str] = []  # when non-empty, cart/selection must match one
    question_contains: str | None = None
```

## Runtime rules

| Surface | catalog-v2 | stores-v1 |
|---|---|---|
| Search | flat `/api/products` | require `store_id`; or `/api/stores/{store_id}/products` |
| `list_stores` | n/a | new tool / `GET /api/stores` |
| Cart key | `product_id` | `listing_id` (fallback: `{store_id}:{product_id}`) |
| Mutations | by `product_id` | by `listing_id` when set |
| Scoring | `valid_product_ids` | prefer `valid_listing_ids` if present |
| Compat export | n/a | `canonical_store_id` row → flat Product |

## Pilot tasks

See `task-multistore-cheapest-shell.draft.json` and `task-multistore-tarn-fell-price.draft.json`.
