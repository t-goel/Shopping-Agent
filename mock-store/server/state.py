"""Resettable catalog and cart state for one sequential benchmark trial."""

from pathlib import Path
from threading import RLock

from pydantic import BaseModel, Field

from shopping_agent.contracts import CatalogExample, Product, TaskDefinition
from shopping_agent.example_checks import expected_products


ROOT = Path(__file__).resolve().parents[2]
CATALOG_PATH = ROOT / "mock-store/server/examples/catalog.json"
TASKS_PATH = ROOT / "data/tasks"


# Reject invalid examples and wrong expected answers before the store accepts any trial.
def load_examples(
    catalog_path: Path = CATALOG_PATH, tasks_path: Path = TASKS_PATH
) -> tuple[CatalogExample, dict[str, TaskDefinition]]:
    catalog = CatalogExample.model_validate_json(catalog_path.read_text())
    tasks = {}
    product_ids = {product.product_id for product in catalog.products}
    known_attributes = set(Product.model_fields) | {
        key for product in catalog.products for key in product.attributes
    }
    for path in sorted(tasks_path.glob("*.json")):
        task = TaskDefinition.model_validate_json(path.read_text())
        if task.task_id in tasks:
            raise ValueError(f"duplicate task ID: {task.task_id}")

        if task.catalog_version != catalog.version:
            raise ValueError(f"{path}: catalog version mismatch")

        for constraint in task.request.constraints:
            if constraint.attribute not in known_attributes:
                raise ValueError(f"{path}: unknown constraint attribute {constraint.attribute}")

        for product_id in task.expected.valid_product_ids:
            if product_id not in product_ids:
                raise ValueError(f"{path}: unknown expected product {product_id}")

        for mutation in task.mutations:
            if mutation.product_id not in product_ids:
                raise ValueError(f"{path}: unknown mutation product {mutation.product_id}")

        if task.expected.kind != "clarification":
            actual = expected_products(catalog, task)
            expected = set(task.expected.valid_product_ids)

            if actual != expected:
                raise ValueError(f"{path}: expected products {sorted(expected)}, computed {sorted(actual)}")

        tasks[task.task_id] = task
    
    if not tasks:
        raise ValueError("no task examples found")

    return catalog, tasks


class CartItem(BaseModel):
    product_id: str
    quantity: int = Field(ge=1)
    unit_price: float
    line_total: float
    in_stock: bool
    listing_id: str | None = None
    store_id: str | None = None


class Cart(BaseModel):
    items: list[CartItem]
    total: float
    currency: str = "USD"


class StoreError(Exception):
    def __init__(self, message: str, status: int):
        super().__init__(message)
        self.status = status


class Store:
    """One local store instance; the runner resets it between sequential trials."""

    def __init__(self, catalog: CatalogExample, tasks: dict[str, TaskDefinition]):
        self.catalog = catalog
        self.tasks = tasks
        self._lock = RLock()
        self.reset()

    def reset(self, task_id: str | None = None) -> dict:
        """Restore catalog, cart, and scheduled events from the selected task example."""
        with self._lock:
            if task_id is not None and task_id not in self.tasks:
                raise StoreError("unknown task", 404)

            self.task_id = task_id
            self.products = {p.product_id: p.model_copy(deep=True) for p in self.catalog.products}
            self.cart: dict[str, int] = {}
            self.observations = 0
            self.applied_mutations: set[int] = set()
            return {"task_id": task_id, "catalog_version": self.catalog.version}

    # Apply each scheduled price or stock change exactly once before the next interaction.
    def _apply_due_mutations(self) -> None:
        mutations = self.tasks[self.task_id].mutations if self.task_id else []
        for index, mutation in enumerate(mutations):
            if index not in self.applied_mutations and self.observations >= mutation.after_observations:
                product = self.products[mutation.product_id]

                if mutation.price is not None:
                    product.price = mutation.price

                if mutation.stock is not None:
                    product.stock = mutation.stock
                self.applied_mutations.add(index)

    # Search the current catalog with all query words and a stable sponsored-first order.
    def search(self, query: str = "", limit: int = 20) -> list[Product]:
        with self._lock:
            self._apply_due_mutations()
            terms = query.casefold().split()
            matched = [
                product for product in self.products.values()
                if all(
                    term in " ".join([
                        product.title, product.description, product.category,
                        *[str(v) for v in product.attributes.values()],
                    ]).casefold() for term in terms
                )
            ]
            matched.sort(key=lambda p: (not p.sponsored, p.product_id))
            self.observations += 1
            return [p.model_copy(deep=True) for p in matched[:limit]]

    def get_product(self, product_id: str) -> Product:
        with self._lock:
            self._apply_due_mutations()
            product = self.products.get(product_id)
            if product is None:
                raise StoreError("product not found", 404)
            self.observations += 1
            return product.model_copy(deep=True)

    def get_cart(self) -> Cart:
        with self._lock:
            self._apply_due_mutations()
            items = [
                CartItem(
                    product_id=product_id,
                    quantity=quantity,
                    unit_price=self.products[product_id].price,
                    line_total=round(self.products[product_id].price * quantity, 2),
                    in_stock=self.products[product_id].stock >= quantity,
                )
                for product_id, quantity in self.cart.items()
            ]
            return Cart(items=items, total=round(sum(item.line_total for item in items), 2))

    def add_to_cart(self, product_id: str, quantity: int) -> Cart:
        """Check live stock and price before changing the cart; never place an order."""
        with self._lock:
            self._apply_due_mutations()
            product = self.products.get(product_id)
            if product is None:
                raise StoreError("product not found", 404)

            if quantity < 1:
                raise StoreError("quantity must be positive", 422)

            if self.cart.get(product_id, 0) + quantity > product.stock:
                raise StoreError("insufficient stock", 409)

            self.cart[product_id] = self.cart.get(product_id, 0) + quantity
            return self.get_cart()

    def snapshot(self) -> dict:
        """Expose ground-truth state to the local evaluator, never the shopping UI."""
        with self._lock:
            self._apply_due_mutations()
            return {
                "task_id": self.task_id,
                "catalog_version": self.catalog.version,
                "observations": self.observations,
                "applied_mutations": sorted(self.applied_mutations),
                "products": {key: value.model_dump(mode="json") for key, value in self.products.items()},
                "cart": self.get_cart().model_dump(),
            }
