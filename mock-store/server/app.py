"""FastAPI routes for the mock storefront and local benchmark control."""

from datetime import datetime, timezone

from fastapi import FastAPI, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, model_validator

from shopping_agent.contracts import Product, Review, StoreRecord, listing_id_for
from server.state import Cart, Store, StoreError, load_examples
from server.multi_store import MultiStore


class ResetRequest(BaseModel):
    task_id: str | None = None


class AddItem(BaseModel):
    product_id: str | None = None
    quantity: int = Field(ge=1)
    listing_id: str | None = None
    store_id: str | None = None

    @model_validator(mode="after")
    def check_identifier(self):
        if self.listing_id:
            return self
        if self.product_id and self.store_id:
            return self
        if self.product_id:
            return self  # single-store cart path
        raise ValueError("listing_id or product_id is required")


class Listing(BaseModel):
    product_id: str
    title: str
    description: str
    category: str
    price: float
    currency: str
    stock: int
    seller: str
    attributes: dict
    sponsored: bool
    rating: float | None
    review_count: int
    reviews: list[Review]
    image_url: str | None
    source_url: str
    observed_at: datetime
    catalog_version: str
    store_id: str | None = None
    listing_id: str | None = None


def as_listing(
    product: Product,
    request: Request,
    catalog_version: str,
    store_id: str | None = None,
    listing_id: str | None = None,
) -> Listing:
    if listing_id:
        try:
            source_url = str(request.url_for("get_listing_by_id", listing_id=listing_id))
        except Exception:
            source_url = f"/api/listings/{listing_id}"
    else:
        try:
            source_url = str(request.url_for("get_product", product_id=product.product_id))
        except Exception:
            source_url = f"/api/products/{product.product_id}"

    return Listing(
        **product.model_dump(exclude={"reviews", "image_url"}),
        reviews=product.reviews,
        image_url=str(product.image_url) if product.image_url else None,
        rating=round(sum(r.rating for r in product.reviews) / len(product.reviews), 2)
        if product.reviews
        else None,
        review_count=len(product.reviews),
        source_url=source_url,
        observed_at=datetime.now(timezone.utc),
        catalog_version=catalog_version,
        store_id=store_id,
        listing_id=listing_id,
    )


def _catalog_version(store: Store | MultiStore) -> str:
    return store.catalog_version if isinstance(store, MultiStore) else store.catalog.version


# Serve one injected trial store in tests or load versioned examples for local development.
def create_app(store: Store | MultiStore | None = None) -> FastAPI:
    if store is None:
        catalog, tasks = load_examples()
        store = Store(catalog, tasks)

    app = FastAPI(title="Mock shopping store", description="Local-only benchmark environment")
    app.state.store = store
    catalog_version = _catalog_version(store)

    @app.exception_handler(StoreError)
    async def store_error(_request: Request, exc: StoreError):
        return JSONResponse(status_code=exc.status, content={"detail": str(exc)})

    @app.get("/api/stores", response_model=list[StoreRecord])
    def list_stores():
        return store.get_stores()

    @app.get("/api/stores/{store_id}/products", response_model=list[Listing])
    def search_store_products(
        store_id: str,
        request: Request,
        q: str = Query(default="", max_length=200),
        limit: int = Query(default=20, ge=1, le=50),
    ):
        if not isinstance(store, MultiStore):
            raise StoreError("store-scoped search not supported on single-store", 404)
        products = store.search(q, limit, store_id=store_id)
        return [
            as_listing(
                product,
                request,
                catalog_version,
                store_id=store_id,
                listing_id=listing_id_for(store_id, product.product_id),
            )
            for product in products
        ]

    @app.get("/api/listings/{listing_id}", response_model=Listing)
    def get_listing_by_id(listing_id: str, request: Request):
        listing = store.get_listing(listing_id)
        product = store.as_product_view(listing)
        return as_listing(
            product,
            request,
            catalog_version,
            store_id=listing.store_id,
            listing_id=listing.listing_id,
        )

    @app.get("/api/products", response_model=list[Listing])
    def search_products(
        request: Request,
        q: str = Query(default="", max_length=200),
        limit: int = Query(default=20, ge=1, le=50),
        store_id: str | None = Query(default=None),
    ):
        # Multi-store requires store_id (no federated search); single-store ignores it.
        products = store.search(q, limit, store_id=store_id)
        return [
            as_listing(
                product,
                request,
                catalog_version,
                store_id=store_id,
                listing_id=listing_id_for(store_id, product.product_id) if store_id else None,
            )
            for product in products
        ]

    @app.get("/api/products/{product_id}", response_model=Listing)
    def get_product(
        product_id: str,
        request: Request,
        store_id: str | None = Query(default=None),
    ):
        product = store.get_product(product_id, store_id=store_id)
        resolved_store = store_id
        lid = None
        if isinstance(store, MultiStore):
            if resolved_store is None:
                resolved_store = store.products[product_id].canonical_store_id
            lid = listing_id_for(resolved_store, product_id)
        return as_listing(
            product,
            request,
            catalog_version,
            store_id=resolved_store,
            listing_id=lid,
        )

    @app.get("/api/products/{product_id}/reviews", response_model=list[Review])
    def get_reviews(product_id: str):
        return store.get_product(product_id).reviews

    @app.get("/api/cart", response_model=Cart)
    def get_cart():
        return store.get_cart()

    @app.post("/api/cart", response_model=Cart)
    def add_to_cart(item: AddItem):
        return store.add_to_cart(
            product_id=item.product_id,
            quantity=item.quantity,
            listing_id=item.listing_id,
            store_id=item.store_id,
        )

    # Keep control paths outside the storefront's /api development proxy.
    @app.post("/internal/reset")
    def reset(request: ResetRequest):
        return store.reset(request.task_id)

    @app.get("/internal/state")
    def state():
        return store.snapshot()

    return app


app = create_app()
