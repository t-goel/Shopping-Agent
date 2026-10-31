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
        if not self.product_id and not self.listing_id:
            raise ValueError("product_id or listing_id is required")
        return self


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


# Serve one injected trial store in tests or load versioned examples for local development.
def create_app(store: Store | MultiStore | None = None) -> FastAPI:
    if store is None:
        catalog, tasks = load_examples()
        store = Store(catalog, tasks)

    app = FastAPI(title="Mock shopping store", description="Local-only benchmark environment")
    app.state.store = store

    catalog_version = (
        store.catalog_version if isinstance(store, MultiStore) else store.catalog.version
    )

    @app.exception_handler(StoreError)
    async def store_error(_request: Request, exc: StoreError):
        return JSONResponse(status_code=exc.status, content={"detail": str(exc)})

    @app.get("/api/stores", response_model=list[StoreRecord])
    def list_stores():
        if isinstance(store, MultiStore):
            return store.get_stores()
        raise StoreError("stores endpoint not supported in single-store mode", 404)

    @app.get("/api/stores/{store_id}/products", response_model=list[Listing])
    def search_store_products(
        store_id: str,
        request: Request,
        q: str = Query(default="", max_length=200),
        limit: int = Query(default=20, ge=1, le=50),
    ):
        if isinstance(store, MultiStore):
            products = store.search(store_id, q, limit)
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
        raise StoreError("store-scoped search not supported on single-store", 404)

    @app.get("/api/listings/{listing_id}", response_model=Listing)
    def get_listing_by_id(listing_id: str, request: Request):
        if isinstance(store, MultiStore):
            listing = store.get_listing(listing_id)
            product = store.as_product_view(listing)
            return as_listing(
                product,
                request,
                catalog_version,
                store_id=listing.store_id,
                listing_id=listing.listing_id,
            )
        raise StoreError("listing endpoint not supported on single-store", 404)

    @app.get("/api/products", response_model=list[Listing])
    def search_products(
        request: Request,
        q: str = Query(default="", max_length=200),
        limit: int = Query(default=20, ge=1, le=50),
        store_id: str | None = Query(default=None),
    ):
        # Shared search surface: single-store ignores store_id; multi-store requires it
        # (no federated search) so CatalogAPI.search(SearchInput) keeps working.
        if isinstance(store, MultiStore):
            if not store_id:
                raise StoreError("search in multi-store mode requires store_id", 400)
            products = store.search(store_id, q, limit)
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
        return [
            as_listing(product, request, store.catalog.version)
            for product in store.search(q, limit)
        ]

    @app.get("/api/products/{product_id}", response_model=Listing)
    def get_product(
        product_id: str,
        request: Request,
        store_id: str | None = Query(default=None),
    ):
        if isinstance(store, MultiStore):
            if store_id:
                product = store.get_product(store_id, product_id)
                lid = listing_id_for(store_id, product_id)
            else:
                product = store.get_product(product_id)
                ingest_product = store.products[product_id]
                store_id = ingest_product.canonical_store_id
                lid = listing_id_for(store_id, product_id)
            return as_listing(
                product,
                request,
                store.catalog_version,
                store_id=store_id,
                listing_id=lid,
            )
        return as_listing(store.get_product(product_id), request, store.catalog.version)

    @app.get("/api/products/{product_id}/reviews", response_model=list[Review])
    def get_reviews(product_id: str):
        if isinstance(store, MultiStore):
            return store.get_product(product_id).reviews
        return store.get_product(product_id).reviews

    @app.get("/api/cart", response_model=Cart)
    def get_cart():
        return store.get_cart()

    @app.post("/api/cart", response_model=Cart)
    def add_to_cart(item: AddItem):
        if isinstance(store, MultiStore):
            return store.add_to_cart(
                listing_id=item.listing_id,
                product_id=item.product_id,
                quantity=item.quantity,
                store_id=item.store_id,
            )
        if not item.product_id:
            raise StoreError("product_id is required", 422)
        return store.add_to_cart(item.product_id, item.quantity)

    # Keep control paths outside the storefront's /api development proxy.
    @app.post("/internal/reset")
    def reset(request: ResetRequest):
        return store.reset(request.task_id)

    @app.get("/internal/state")
    def state():
        return store.snapshot()

    return app


app = create_app()
