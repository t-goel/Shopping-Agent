"""FastAPI routes for the mock storefront and local benchmark control."""

from datetime import datetime, timezone

from fastapi import FastAPI, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from shopping_agent.contracts import Product, Review
from server.state import Cart, Store, StoreError, load_examples


class ResetRequest(BaseModel):
    task_id: str | None = None


class AddItem(BaseModel):
    product_id: str
    quantity: int = Field(ge=1)


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


def as_listing(product: Product, request: Request, catalog_version: str) -> Listing:
    return Listing(
        **product.model_dump(exclude={"reviews", "image_url"}),
        reviews=product.reviews,
        image_url=str(product.image_url) if product.image_url else None,
        rating=round(sum(r.rating for r in product.reviews) / len(product.reviews), 2)
        if product.reviews
        else None,
        review_count=len(product.reviews),
        source_url=str(request.url_for("get_product", product_id=product.product_id)),
        observed_at=datetime.now(timezone.utc),
        catalog_version=catalog_version,
    )


# Serve one injected trial store in tests or load versioned examples for local development.
def create_app(store: Store | None = None) -> FastAPI:
    if store is None:
        catalog, tasks = load_examples()
        store = Store(catalog, tasks)

    app = FastAPI(title="Mock shopping store", description="Local-only benchmark environment")
    app.state.store = store

    @app.exception_handler(StoreError)
    async def store_error(_request: Request, exc: StoreError):
        return JSONResponse(status_code=exc.status, content={"detail": str(exc)})

    @app.get("/api/products", response_model=list[Listing])
    def search_products(
        request: Request,
        q: str = Query(default="", max_length=200),
        limit: int = Query(default=20, ge=1, le=50),
    ):
        return [
            as_listing(product, request, store.catalog.version)
            for product in store.search(q, limit)
        ]

    @app.get("/api/products/{product_id}", response_model=Listing)
    def get_product(product_id: str, request: Request):
        return as_listing(store.get_product(product_id), request, store.catalog.version)

    @app.get("/api/products/{product_id}/reviews", response_model=list[Review])
    def get_reviews(product_id: str):
        return store.get_product(product_id).reviews

    @app.get("/api/cart", response_model=Cart)
    def get_cart():
        return store.get_cart()

    @app.post("/api/cart", response_model=Cart)
    def add_to_cart(item: AddItem):
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
