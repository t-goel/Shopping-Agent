"""Prototype: project multi-store assortment → flat catalog-v2 products (compat mode).

Overlap SKUs keep the cheapest in-stock listing's price/stock; sponsored is OR'd.
This is exploration-only — not wired into the mock store loader.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CATALOG = ROOT / "mock-store/server/examples/catalog.json"
PARTITION = Path(__file__).with_name("stores-partition-v1.json")


def project(catalog: dict, partition: dict) -> dict:
    by_id = {p["product_id"]: dict(p) for p in catalog["products"]}
    listings: dict[str, list[dict]] = defaultdict(list)
    for row in partition["assortment"]:
        listings[row["product_id"]].append(row)

    missing = sorted(set(by_id) - set(listings))
    if missing:
        raise SystemExit(f"partition missing products: {missing}")

    projected = []
    for product_id, product in by_id.items():
        rows = listings[product_id]
        # Prefer in-stock, then lowest price, then listing_id for stability.
        ranked = sorted(
            rows,
            key=lambda r: (r["stock"] <= 0, r["price"], r["listing_id"]),
        )
        chosen = ranked[0]
        out = dict(product)
        out["price"] = chosen["price"]
        out["stock"] = chosen["stock"]
        out["sponsored"] = any(r["sponsored"] for r in rows)
        out["_compat_from_listing"] = chosen["listing_id"]
        out["_overlap_store_ids"] = sorted({r["store_id"] for r in rows})
        projected.append(out)

    return {
        "version": f"{catalog['version']}+stores-compat",
        "products": projected,
        "meta": {
            "stores": [s["store_id"] for s in partition["stores"]],
            "overlap_product_ids": sorted(
                pid for pid, rows in listings.items() if len(rows) > 1
            ),
            "warning": (
                "Compat mode collapses overlap prices to one Product; "
                "multi-mode must keep listing_id identity."
            ),
        },
    }


def main() -> None:
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    partition = json.loads(PARTITION.read_text(encoding="utf-8"))
    result = project(catalog, partition)
    out_path = Path(__file__).with_name("catalog-v2-stores-compat.json")
    out_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    overlaps = result["meta"]["overlap_product_ids"]
    print(f"wrote {out_path}")
    print(f"products={len(result['products'])} overlaps={overlaps}")
    for pid in overlaps:
        p = next(x for x in result["products"] if x["product_id"] == pid)
        print(
            f"  {pid}: compat price={p['price']} from {p['_compat_from_listing']} "
            f"stores={p['_overlap_store_ids']}"
        )


if __name__ == "__main__":
    main()
