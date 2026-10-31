"""Multi-store catalog and cart state for stores-v1 benchmark trials."""

from __future__ import annotations

from pathlib import Path
from threading import RLock

from shopping_agent.contracts import (
    AssortmentRow,
    IngestCatalog,
    IngestProduct,
    Product,
    StoreRecord,
    TaskDefinition,
    listing_id_for,
    resolve_mutation_rows,
)
from shopping_agent.example_checks import expected_listings
from shopping_agent.ingest import load_ingest
from server.state import Cart, CartItem, StoreError, product_matches_query

ROOT = Path(__file__).resolve().parents[2]
INGEST_PATH = ROOT / "mock-store/server/examples/ingest-v1.example.json"
STORES_TASKS_PATH = ROOT / "data/tasks/stores"


def load_multi_store_examples(
    ingest_path: Path = INGEST_PATH, tasks_path: Path = STORES_TASKS_PATH
) -> tuple[IngestCatalog, dict[str, TaskDefinition]]:
    """Load ingest-v1 catalog and multi-store task definitions."""
    ingest = load_ingest(ingest_path)
    tasks: dict[str, TaskDefinition] = {}

    listing_ids = {row.listing_id for row in ingest.assortment}
    product_ids = {product.product_id for product in ingest.products}

    if tasks_path.exists():
        for path in sorted(tasks_path.glob("*.json")):
            task = TaskDefinition.model_validate_json(path.read_text(encoding="utf-8"))
            if task.task_id in tasks:
                raise ValueError(f"duplicate task ID: {task.task_id}")

            for listing_id in task.expected.valid_listing_ids:
                if listing_id not in listing_ids:
                    raise ValueError(f"{path}: unknown expected listing {listing_id}")

            for product_id in task.expected.valid_product_ids:
                if product_id not in product_ids:
                    raise ValueError(f"{path}: unknown expected product {product_id}")

            for mutation in task.mutations:
                if mutation.listing_id and mutation.listing_id not in listing_ids:
                    raise ValueError(f"{path}: unknown mutation listing {mutation.listing_id}")
                if mutation.product_id and mutation.product_id not in product_ids:
                    raise ValueError(f"{path}: unknown mutation product {mutation.product_id}")

            if task.expected.kind != "clarification" and task.expected.valid_listing_ids:
                actual = expected_listings(ingest, task)
                expected = set(task.expected.valid_listing_ids)
                if actual != expected:
                    raise ValueError(
                        f"{path}: expected listings {sorted(expected)}, computed {sorted(actual)}"
                    )

            tasks[task.task_id] = task

    return ingest, tasks


class MultiStore:
    """Multi-store mock runtime supporting store-scoped search, listing-keyed cart, and mutations."""

    def __init__(
        self,
        ingest: IngestCatalog | dict,
        tasks: dict[str, TaskDefinition] | None = None,
    ):
        if isinstance(ingest, IngestCatalog):
            self.ingest = ingest
        else:
            self.ingest = IngestCatalog.model_validate(ingest)

        self.tasks = tasks or {}
        self.catalog_version = "stores-v1"
        self.stores: dict[str, StoreRecord] = {s.store_id: s for s in self.ingest.stores}
        self.products: dict[str, IngestProduct] = {
            p.product_id: p for p in self.ingest.products
        }
        self._initial_listings: dict[str, AssortmentRow] = {
            r.listing_id: r.model_copy(deep=True) for r in self.ingest.assortment
        }
        self._lock = RLock()
        self.reset()

    def reset(self, task_id: str | None = None) -> dict:
        """Restore initial listings, cart, and scheduled mutations."""
        with self._lock:
            if task_id is not None and task_id not in self.tasks:
                raise StoreError("unknown task", 404)

            self.task_id = task_id
            self.listings: dict[str, AssortmentRow] = {
                k: v.model_copy(deep=True) for k, v in self._initial_listings.items()
            }
            self.cart: dict[str, int] = {}
            self.observations = 0
            self.applied_mutations: set[int] = set()
            return {"task_id": task_id, "catalog_version": self.catalog_version}

    def _apply_due_mutations(self) -> None:
        mutations = (
            self.tasks[self.task_id].mutations
            if (self.task_id and self.task_id in self.tasks)
            else []
        )
        for index, mutation in enumerate(mutations):
            if (
                index not in self.applied_mutations
                and self.observations >= mutation.after_observations
            ):
                target_rows = resolve_mutation_rows(mutation, self.listings)
                for row in target_rows:
                    if mutation.price is not None:
                        row.price = mutation.price
                    if mutation.stock is not None:
                        row.stock = mutation.stock

                self.applied_mutations.add(index)

    def get_stores(self) -> list[StoreRecord]:
        """List all available stores."""
        with self._lock:
            return list(self.stores.values())

    def as_product_view(self, listing: AssortmentRow | str) -> Product:
        """Project listing price/stock/sponsored onto canonical Product for API compat."""
        if isinstance(listing, str):
            listing_obj = self.listings.get(listing)
            if listing_obj is None:
                raise StoreError("listing not found", 404)
        else:
            listing_obj = listing

        product = self.products[listing_obj.product_id]
        return Product(
            product_id=product.product_id,
            title=product.title,
            description=product.description,
            category=product.category,
            price=listing_obj.price,
            currency=product.currency,
            stock=listing_obj.stock,
            seller=product.seller_default,
            attributes=product.attributes,
            reviews=product.reviews,
            sponsored=listing_obj.sponsored,
            image_url=product.image_url,
        )

    def search(
        self, query: str = "", limit: int = 20, store_id: str | None = None
    ) -> list[Product]:
        """Search products within a specific store. Requires store_id."""
        with self._lock:
            self._apply_due_mutations()
            if not store_id:
                raise StoreError("store_id is required", 400)
            if store_id not in self.stores:
                raise StoreError(f"unknown store_id: {store_id}", 400)

            matched: list[AssortmentRow] = []
            for listing in self.listings.values():
                if listing.store_id != store_id:
                    continue
                product = self.as_product_view(listing)
                if not product_matches_query(product, query):
                    continue
                matched.append(listing)

            matched.sort(key=lambda row: (not row.sponsored, row.listing_id))
            self.observations += 1
            return [self.as_product_view(row) for row in matched[:limit]]

    def get_listing(self, listing_id: str) -> AssortmentRow:
        """Get live assortment row by listing_id."""
        with self._lock:
            self._apply_due_mutations()
            listing = self.listings.get(listing_id)
            if listing is None:
                raise StoreError("listing not found", 404)
            self.observations += 1
            return listing.model_copy(deep=True)

    def get_product(self, product_id: str, store_id: str | None = None) -> Product:
        """Get product view by (store_id, product_id) or canonical store when store_id omitted."""
        with self._lock:
            self._apply_due_mutations()
            if store_id is None:
                product = self.products.get(product_id)
                if product is None:
                    raise StoreError("product not found", 404)
                listing_id = listing_id_for(product.canonical_store_id, product_id)
            else:
                if store_id not in self.stores:
                    raise StoreError(f"unknown store_id: {store_id}", 400)
                listing_id = listing_id_for(store_id, product_id)
            listing = self.listings.get(listing_id)
            if listing is None:
                raise StoreError("listing not found", 404)
            self.observations += 1
            return self.as_product_view(listing)

    def get_cart(self) -> Cart:
        """Get current cart keyed by listing_id."""
        with self._lock:
            self._apply_due_mutations()
            items = [
                CartItem(
                    product_id=self.listings[listing_id].product_id,
                    listing_id=listing_id,
                    store_id=self.listings[listing_id].store_id,
                    quantity=quantity,
                    unit_price=self.listings[listing_id].price,
                    line_total=round(self.listings[listing_id].price * quantity, 2),
                    in_stock=self.listings[listing_id].stock >= quantity,
                )
                for listing_id, quantity in self.cart.items()
            ]
            total = round(sum(item.line_total for item in items), 2)
            return Cart(items=items, total=total, currency="USD")

    def add_to_cart(
        self,
        product_id: str | None = None,
        quantity: int = 1,
        *,
        listing_id: str | None = None,
        store_id: str | None = None,
    ) -> Cart:
        """Add to cart using listing_id or (store_id, product_id). No silent canonical fallback."""
        with self._lock:
            self._apply_due_mutations()
            if quantity < 1:
                raise StoreError("quantity must be positive", 422)

            if listing_id:
                target_listing_id = listing_id
            elif store_id and product_id:
                target_listing_id = listing_id_for(store_id, product_id)
            else:
                raise StoreError(
                    "listing_id or (store_id and product_id) required",
                    422,
                )

            listing = self.listings.get(target_listing_id)
            if listing is None:
                raise StoreError("listing not found", 404)

            current_qty = self.cart.get(target_listing_id, 0)
            if current_qty + quantity > listing.stock:
                raise StoreError("insufficient stock", 409)

            self.cart[target_listing_id] = current_qty + quantity
            return self.get_cart()

    def snapshot(self) -> dict:
        """Expose ground-truth state for evaluators."""
        with self._lock:
            self._apply_due_mutations()
            return {
                "task_id": self.task_id,
                "catalog_version": self.catalog_version,
                "observations": self.observations,
                "applied_mutations": sorted(self.applied_mutations),
                "stores": [s.model_dump(mode="json") for s in self.stores.values()],
                "products": {k: v.model_dump(mode="json") for k, v in self.products.items()},
                "listings": {k: v.model_dump(mode="json") for k, v in self.listings.items()},
                "cart": self.get_cart().model_dump(),
            }
