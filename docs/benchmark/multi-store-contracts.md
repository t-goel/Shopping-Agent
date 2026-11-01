# Multi-store contracts

Current contracts in `contracts.py`. No staged catalog/stores version cutover — iterate on these fields directly. Flat single-catalog mode remains available via `cli run --mode flat` for the NL suite.

## Models

```python
class StoreRecord(Contract):
    store_id: str  # kebab-case
    name: str
    brand_seller: str  # chrome only

class SearchInput(Contract):
    query: str
    max_results: int = 20
    store_id: str | None = None  # multi-store API requires it (400 if missing)

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
    listing_id: str | None = None

class ExpectedOutcome(Contract):
    kind: Literal["product", "no_valid_product", "clarification"]
    valid_product_ids: list[str] = []
    valid_listing_ids: list[str] = []
    question_contains: str | None = None
```

## Runtime rules

| Surface | flat | multi-store |
|---|---|---|
| Search | `/api/products` | require `store_id`; or `/api/stores/{store_id}/products` |
| `list_stores` | 404 | `GET /api/stores` |
| Cart key | `product_id` | `listing_id` |
| Mutations | by `product_id` | by `listing_id` / `store_id` when set |
| Scoring | `valid_product_ids` | prefer `valid_listing_ids` |
| Compat export | n/a | `canonical_store_id` → flat Product |

## Suite

Default CLI mode is multi-store (`data/tasks/stores`). Flat NL suite: `--mode flat`.
