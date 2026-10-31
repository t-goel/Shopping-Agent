"""Prototype projectors for ingest-v1 → compat Product list / multi-store listings.

Exploration-only — not wired into the mock store loader or NL suite.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
INGEST_SAMPLE = HERE / "ingest-v1.sample.json"


def _validate_listing_ids(ingest: dict) -> None:
    store_ids = {s["store_id"] for s in ingest["stores"]}
    product_ids = {p["product_id"] for p in ingest["products"]}
    seen: set[tuple[str, str]] = set()
    for row in ingest["assortment"]:
        key = (row["store_id"], row["product_id"])
        if key in seen:
            raise ValueError(f"duplicate assortment row {key}")
        seen.add(key)
        if row["store_id"] not in store_ids:
            raise ValueError(f"unknown store_id {row['store_id']}")
        if row["product_id"] not in product_ids:
            raise ValueError(f"unknown product_id {row['product_id']}")
        expected = f"{row['store_id']}:{row['product_id']}"
        if row["listing_id"] != expected:
            raise ValueError(f"listing_id {row['listing_id']!r} != {expected!r}")
    for product in ingest["products"]:
        canonical = product.get("canonical_store_id")
        if not canonical:
            raise ValueError(f"{product['product_id']}: canonical_store_id is required")
        if canonical not in store_ids:
            raise ValueError(
                f"{product['product_id']}: unknown canonical_store_id {canonical!r}"
            )
        if (canonical, product["product_id"]) not in seen:
            raise ValueError(
                f"{product['product_id']}: no assortment row for canonical_store_id {canonical!r}"
            )


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


def project_compat(ingest: dict) -> dict:
    """One Product per product_id; price/stock from canonical_store_id listing."""
    _validate_listing_ids(ingest)
    by_id = {p["product_id"]: p for p in ingest["products"]}
    listings: dict[str, list[dict]] = defaultdict(list)
    for row in ingest["assortment"]:
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
            "ingest_version": ingest["ingest_version"],
            "stores": [s["store_id"] for s in ingest["stores"]],
            "overlap_product_ids": sorted(
                pid for pid, rows in listings.items() if len(rows) > 1
            ),
            "compat_rule": "canonical_store_id listing supplies price/stock/sponsored",
            "warning": "Compat ignores non-canonical overlap offers; multi-mode keeps listing_id.",
        },
    }


def project_multi(ingest: dict) -> dict:
    """Keep one product record; emit store-scoped listings keyed by listing_id."""
    _validate_listing_ids(ingest)
    products = []
    for src in ingest["products"]:
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
    for row in ingest["assortment"]:
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
        "stores": ingest["stores"],
        "products": products,
        "listings": listings,
        "meta": {
            "ingest_version": ingest["ingest_version"],
            "listing_count": len(listings),
            "overlap_product_ids": sorted(
                {
                    pid
                    for pid, n in (
                        (
                            pid,
                            sum(1 for r in ingest["assortment"] if r["product_id"] == pid),
                        )
                        for pid in by_id
                    )
                    if n > 1
                }
            ),
        },
    }


def main() -> None:
    ingest = json.loads(INGEST_SAMPLE.read_text(encoding="utf-8"))
    compat = project_compat(ingest)
    multi = project_multi(ingest)
    compat_path = HERE / "ingest-v1.compat.json"
    multi_path = HERE / "ingest-v1.multi.json"
    compat_path.write_text(json.dumps(compat, indent=2) + "\n", encoding="utf-8")
    multi_path.write_text(json.dumps(multi, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {compat_path}")
    print(f"wrote {multi_path}")
    print(
        f"compat products={len(compat['products'])} "
        f"overlaps={compat['meta']['overlap_product_ids']}"
    )
    print(
        f"multi listings={multi['meta']['listing_count']} "
        f"overlaps={multi['meta']['overlap_product_ids']}"
    )


if __name__ == "__main__":
    main()
