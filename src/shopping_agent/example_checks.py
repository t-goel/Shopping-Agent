"""Authoring checks for benchmark examples; these are never exposed to the agent."""

from shopping_agent.comparison import matches
from shopping_agent.contracts import (
    AssortmentRow,
    CatalogExample,
    IngestCatalog,
    Product,
    TaskDefinition,
)


def _rating(product: Product) -> float:
    if not product.reviews:
        return -1
    return sum(r.rating for r in product.reviews) / len(product.reviews)


# Compute valid winners after scheduled changes, keeping ties as equally valid answers.
def expected_products(catalog: CatalogExample, task: TaskDefinition) -> set[str]:
    products = {
        product.product_id: product.model_copy(deep=True)
        for product in catalog.products
    }

    for mutation in task.mutations:
        product = products[mutation.product_id]

        if mutation.price is not None:
            product.price = mutation.price

        if mutation.stock is not None:
            product.stock = mutation.stock

    candidates = [
        product for product in products.values()
        if product.stock > 0 and all(matches(product, c) for c in task.request.constraints if c.hard)
    ]

    if not candidates:
        return set()

    if task.ranking_rule == "lowest_price":
        best = min(product.price for product in candidates)
        candidates = [product for product in candidates if product.price == best]

    elif task.ranking_rule in {"highest_rating", "highest_rating_then_reviews"}:
        best = max(_rating(product) for product in candidates)
        candidates = [product for product in candidates if _rating(product) == best]

        if task.ranking_rule == "highest_rating_then_reviews" and len(candidates) > 1:
            most_reviews = max(len(product.reviews) for product in candidates)
            candidates = [
                product for product in candidates if len(product.reviews) == most_reviews
            ]

    return {product.product_id for product in candidates}


def _listing_as_product(ingest: IngestCatalog, row: AssortmentRow) -> Product:
    product = next(p for p in ingest.products if p.product_id == row.product_id)
    return Product(
        product_id=product.product_id,
        title=product.title,
        description=product.description,
        category=product.category,
        currency=product.currency,
        seller=product.seller_default,
        attributes=product.attributes,
        reviews=product.reviews,
        image_url=product.image_url,
        price=row.price,
        stock=row.stock,
        sponsored=row.sponsored,
    )


def expected_listings(ingest: IngestCatalog, task: TaskDefinition) -> set[str]:
    """Compute winning listing_ids for a stores-v1 task after scheduled mutations."""
    listings = {
        row.listing_id: row.model_copy(deep=True) for row in ingest.assortment
    }

    for mutation in task.mutations:
        targets: list[AssortmentRow] = []
        if mutation.listing_id and mutation.listing_id in listings:
            targets = [listings[mutation.listing_id]]
        elif mutation.store_id:
            lid = f"{mutation.store_id}:{mutation.product_id}"
            if lid in listings:
                targets = [listings[lid]]
        else:
            targets = [
                row for row in listings.values() if row.product_id == mutation.product_id
            ]
        for row in targets:
            if mutation.price is not None:
                row.price = mutation.price
            if mutation.stock is not None:
                row.stock = mutation.stock

    hard = [c for c in task.request.constraints if c.hard]
    candidates: list[tuple[str, Product]] = []
    for listing_id, row in listings.items():
        product = _listing_as_product(ingest, row)
        if product.stock > 0 and all(matches(product, c) for c in hard):
            candidates.append((listing_id, product))
    if not candidates:
        return set()

    if task.ranking_rule == "lowest_price":
        best = min(product.price for _, product in candidates)
        return {
            listing_id
            for listing_id, product in candidates
            if product.price == best
        }

    if task.ranking_rule in {"highest_rating", "highest_rating_then_reviews"}:
        best = max(_rating(product) for _, product in candidates)
        ranked = [
            (listing_id, product)
            for listing_id, product in candidates
            if _rating(product) == best
        ]
        if task.ranking_rule == "highest_rating_then_reviews" and len(ranked) > 1:
            most = max(len(product.reviews) for _, product in ranked)
            ranked = [
                (listing_id, product)
                for listing_id, product in ranked
                if len(product.reviews) == most
            ]
        return {listing_id for listing_id, _ in ranked}

    return {listing_id for listing_id, _ in candidates}
