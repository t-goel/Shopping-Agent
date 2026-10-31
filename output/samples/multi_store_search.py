"""Prototype: store-scoped search over ingest-v1.multi.json listings.

Requires store_id (multi-mode recommendation). Not wired into mock-store.
"""

from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
MULTI = HERE / "ingest-v1.multi.json"


def search(multi: dict, store_id: str, query: str = "", limit: int = 20) -> list[dict]:
    store_ids = {s["store_id"] for s in multi["stores"]}
    if store_id not in store_ids:
        raise KeyError(f"unknown store_id {store_id!r}; known={sorted(store_ids)}")

    terms = query.casefold().split()
    matched = []
    for listing in multi["listings"]:
        if listing["store_id"] != store_id:
            continue
        hay = " ".join(
            [
                listing["title"],
                listing.get("description", ""),
                listing["category"],
                *[str(v) for v in listing["attributes"].values()],
            ]
        ).casefold()
        if terms and not all(term in hay for term in terms):
            continue
        matched.append(listing)

    matched.sort(key=lambda row: (not row["sponsored"], row["listing_id"]))
    return matched[:limit]


def main() -> None:
    multi = json.loads(MULTI.read_text(encoding="utf-8"))
    demos = [
        ("trailworks-direct", "waterproof"),
        ("summit-outfitters", "waterproof"),
        ("metrowear", "bag"),
        ("clearance-corner", "ridge"),
        ("headwater-supply", ""),
    ]
    for store_id, query in demos:
        hits = search(multi, store_id, query)
        print(f"\n{store_id} q={query!r} -> {len(hits)}")
        for hit in hits:
            print(
                f"  {hit['listing_id']} ${hit['price']} "
                f"stock={hit['stock']} sponsored={hit['sponsored']} "
                f"seller={hit['seller']}"
            )


if __name__ == "__main__":
    main()
