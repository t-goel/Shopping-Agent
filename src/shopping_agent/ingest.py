"""Load, validate, and project ingest-v1 catalogs for single-store compat and multi-store."""

from __future__ import annotations

from collections import defaultdict
import json
from pathlib import Path

from shopping_agent.contracts import (
    CatalogExample,
    IngestCatalog,
    IngestProduct,
    IngestProvenance,
    StoresPartition,
)


def load_ingest(source: Path | str | dict) -> IngestCatalog:
    """Load and validate an ingest-v1 payload from a file path, JSON string, or dict."""
    if isinstance(source, (str, Path)):
        path = Path(source)
        if path.is_file():
            data = json.loads(path.read_text(encoding="utf-8"))
        else:
            data = json.loads(str(source))
    else:
        data = source

    return validate_ingest(data)


def validate_ingest(data: dict | IngestCatalog) -> IngestCatalog:
    """Validate data against IngestCatalog schema and integrity rules."""
    if isinstance(data, IngestCatalog):
        return data
    return IngestCatalog.model_validate(data)


def load_partition(source: Path | str | dict) -> StoresPartition:
    """Load a stores+assortment overlay (accepts notes/blurb; role is informational)."""
    if isinstance(source, (str, Path)):
        path = Path(source)
        if path.is_file():
            data = json.loads(path.read_text(encoding="utf-8"))
        else:
            data = json.loads(str(source))
    else:
        data = source
    return StoresPartition.model_validate(data)


def merge_partition_with_catalog(
    partition: StoresPartition | dict | Path | str,
    catalog: CatalogExample | dict | Path | str,
) -> IngestCatalog:
    """Combine catalog-v2 products with a stores partition into a full ingest-v1 catalog."""
    if not isinstance(partition, StoresPartition):
        partition = load_partition(partition)
    if isinstance(catalog, (str, Path)):
        path = Path(catalog)
        catalog = CatalogExample.model_validate_json(path.read_text(encoding="utf-8"))
    elif isinstance(catalog, dict):
        catalog = CatalogExample.model_validate(catalog)

    product_ids = {p.product_id for p in catalog.products}
    for row in partition.assortment:
        if row.product_id not in product_ids:
            raise ValueError(f"partition references unknown product {row.product_id}")

    # Prefer each product's first assortment store as canonical when building ingest products.
    first_store: dict[str, str] = {}
    for row in partition.assortment:
        first_store.setdefault(row.product_id, row.store_id)

    products = [
        IngestProduct(
            product_id=product.product_id,
            title=product.title,
            description=product.description,
            category=product.category,
            currency=product.currency,
            canonical_store_id=first_store.get(product.product_id, partition.stores[0].store_id),
            seller_default=product.seller,
            attributes=product.attributes,
            reviews=product.reviews,
            image_url=product.image_url,
            provenance=IngestProvenance(
                method="synthetic",
                notes="Projected from catalog + stores partition",
            ),
        )
        for product in catalog.products
        if product.product_id in first_store
    ]
    return IngestCatalog(
        ingest_version="ingest-v1",
        notes=partition.notes,
        catalog_bootstrap=partition.catalog_bootstrap or catalog.version,
        stores=partition.stores,
        products=products,
        assortment=partition.assortment,
    )


def _to_raw_dict(ingest: dict | IngestCatalog) -> dict:
    if isinstance(ingest, IngestCatalog):
        return ingest.model_dump(mode="json")
    # Validate to enforce consistency rules
    return IngestCatalog.model_validate(ingest).model_dump(mode="json")


def _choose_compat_listing(src: dict, rows: list[dict]) -> dict:
    """Price/stock from required canonical_store_id row (catalog-v2-stable)."""
    canonical = src.get("canonical_store_id")
    if not canonical:
        raise ValueError(f"{src['product_id']}: canonical_store_id is required")
    for row in rows:
        if row["store_id"] == canonical:
            return row
    raise ValueError(
        f"{src['product_id']}: canonical_store_id {canonical!r} has no assortment row"
    )


def project_compat(ingest: dict | IngestCatalog) -> dict:
    """One Product per product_id; price/stock from canonical_store_id listing."""
    raw = _to_raw_dict(ingest)
    by_id = {p["product_id"]: p for p in raw["products"]}
    listings: dict[str, list[dict]] = defaultdict(list)
    for row in raw["assortment"]:
        listings[row["product_id"]].append(row)

    products = []
    for product_id, src in by_id.items():
        rows = listings.get(product_id)
        if not rows:
            raise ValueError(f"product {product_id} has no assortment rows")
        chosen = _choose_compat_listing(src, rows)
        products.append(
            {
                "product_id": product_id,
                "title": src["title"],
                "description": src["description"],
                "category": src["category"],
                "price": chosen["price"],
                "currency": src["currency"],
                "stock": chosen["stock"],
                "seller": src["seller_default"],
                "attributes": src["attributes"],
                "reviews": src["reviews"],
                "sponsored": chosen["sponsored"],
                "image_url": src.get("image_url"),
                "_compat_from_listing": chosen["listing_id"],
                "_canonical_store_id": src.get("canonical_store_id"),
                "_overlap_store_ids": sorted({r["store_id"] for r in rows}),
            }
        )

    return {
        "version": "catalog-v2+ingest-compat",
        "products": products,
        "meta": {
            "ingest_version": raw["ingest_version"],
            "stores": [s["store_id"] for s in raw["stores"]],
            "overlap_product_ids": sorted(
                pid for pid, rows in listings.items() if len(rows) > 1
            ),
            "compat_rule": "canonical_store_id listing supplies price/stock/sponsored",
            "warning": "Compat ignores non-canonical overlap offers; multi-mode keeps listing_id.",
        },
    }


def project_multi(ingest: dict | IngestCatalog) -> dict:
    """Keep one product record; emit store-scoped listings keyed by listing_id."""
    raw = _to_raw_dict(ingest)
    products = []
    for src in raw["products"]:
        products.append(
            {
                "product_id": src["product_id"],
                "title": src["title"],
                "description": src["description"],
                "category": src["category"],
                "currency": src["currency"],
                "seller": src["seller_default"],
                "canonical_store_id": src.get("canonical_store_id"),
                "attributes": src["attributes"],
                "reviews": src["reviews"],
                "image_url": src.get("image_url"),
            }
        )
    by_id = {p["product_id"]: p for p in products}
    listings = []
    for row in raw["assortment"]:
        product = by_id[row["product_id"]]
        listings.append(
            {
                "listing_id": row["listing_id"],
                "store_id": row["store_id"],
                "product_id": row["product_id"],
                "price": row["price"],
                "stock": row["stock"],
                "sponsored": row["sponsored"],
                "seller": product["seller"],
                "title": product["title"],
                "description": product["description"],
                "category": product["category"],
                "attributes": product["attributes"],
            }
        )
    return {
        "version": "stores-v1",
        "stores": raw["stores"],
        "products": products,
        "listings": listings,
        "meta": {
            "ingest_version": raw["ingest_version"],
            "listing_count": len(listings),
            "overlap_product_ids": sorted(
                {
                    pid
                    for pid, n in (
                        (
                            pid,
                            sum(1 for r in raw["assortment"] if r["product_id"] == pid),
                        )
                        for pid in by_id
                    )
                    if n > 1
                }
            ),
        },
    }
