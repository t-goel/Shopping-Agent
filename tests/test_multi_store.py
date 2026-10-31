"""Tests for stores-v1 multi-store runtime, ingest projection, and contracts."""

from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from server.app import create_app
from server.multi_store import MultiStore, load_multi_store_examples
from server.state import StoreError
from shopping_agent.contracts import (
    ExpectedOutcome,
    Mutation,
    ShoppingRequest,
    TaskDefinition,
)
from shopping_agent.ingest import load_ingest, project_compat, project_multi

ROOT = Path(__file__).resolve().parents[1]
INGEST_PATH = ROOT / "mock-store/server/examples/ingest-v1.sample.json"


def test_ingest_load_and_canonical_compat_prices():
    ingest = load_ingest(INGEST_PATH)
    assert len(ingest.stores) == 5
    assert len(ingest.products) == 6
    assert len(ingest.assortment) == 10

    compat = project_compat(ingest)
    assert compat["version"] == "catalog-v2+ingest-compat"
    assert len(compat["products"]) == 6
    assert compat["meta"]["overlap_product_ids"] == [
        "harbor-backpack",
        "ridge-shell",
        "tarn-fell",
    ]

    by_id = {p["product_id"]: p for p in compat["products"]}
    # Canonical store prices match sample
    assert by_id["ridge-shell"]["price"] == 89.0
    assert by_id["ridge-shell"]["stock"] == 4
    assert by_id["ridge-shell"]["seller"] == "Trailworks"

    assert by_id["ridge-shell-reseller"]["price"] == 69.0
    assert by_id["harbor-backpack"]["price"] == 64.0
    assert by_id["meadow-sling"]["price"] == 29.0
    assert by_id["headwater-duffel"]["price"] == 149.0

    # tarn-fell uses canonical_store_id (trailworks-direct: $91), not headwater ($88)
    assert by_id["tarn-fell"]["price"] == 91.0
    assert by_id["tarn-fell"]["stock"] == 6
    assert by_id["tarn-fell"]["seller"] == "River Gear"

    multi = project_multi(ingest)
    assert multi["version"] == "stores-v1"
    assert multi["meta"]["listing_count"] == 10
    assert len(multi["listings"]) == 10


def test_store_scoped_search_and_validation():
    ingest, tasks = load_multi_store_examples()
    store = MultiStore(ingest, tasks)

    # Direct store search
    tw_results = store.search("trailworks-direct", "waterproof")
    assert any(p.product_id == "ridge-shell" and p.price == 89.0 for p in tw_results)

    summit_results = store.search("summit-outfitters", "waterproof")
    assert any(p.product_id == "ridge-shell" and p.price == 94.0 for p in summit_results)

    # Missing or unknown store_id raises StoreError 400
    with pytest.raises(StoreError) as exc_missing:
        store.search("", "waterproof")
    assert exc_missing.value.status == 400

    with pytest.raises(StoreError) as exc_unknown:
        store.search("nonexistent-store", "waterproof")
    assert exc_unknown.value.status == 400

    # API endpoints
    with TestClient(create_app(store)) as api:
        stores = api.get("/api/stores").json()
        assert len(stores) == 5
        store_ids = {s["store_id"] for s in stores}
        assert "trailworks-direct" in store_ids
        assert "summit-outfitters" in store_ids

        # trailworks search finds ridge-shell at $89
        tw_resp = api.get(
            "/api/stores/trailworks-direct/products", params={"q": "waterproof"}
        ).json()
        tw_shell = next(item for item in tw_resp if item["product_id"] == "ridge-shell")
        assert tw_shell["price"] == 89.0
        assert tw_shell["seller"] == "Trailworks"
        assert tw_shell["listing_id"] == "trailworks-direct:ridge-shell"
        assert tw_shell["store_id"] == "trailworks-direct"

        # summit search finds ridge-shell at $94
        summit_resp = api.get(
            "/api/stores/summit-outfitters/products", params={"q": "waterproof"}
        ).json()
        summit_shell = next(
            item for item in summit_resp if item["product_id"] == "ridge-shell"
        )
        assert summit_shell["price"] == 94.0
        assert summit_shell["seller"] == "Trailworks"  # seller_default preserved
        assert summit_shell["listing_id"] == "summit-outfitters:ridge-shell"
        assert summit_shell["store_id"] == "summit-outfitters"

        # flat /api/products returns 400 in multi-store mode (no federated search)
        assert api.get("/api/products", params={"q": "waterproof"}).status_code == 400

        # unknown store returns 400
        assert (
            api.get(
                "/api/stores/unknown-store/products", params={"q": "waterproof"}
            ).status_code
            == 400
        )


def test_cart_by_listing_id_and_distinct_lines():
    ingest, tasks = load_multi_store_examples()
    store = MultiStore(ingest, tasks)

    with TestClient(create_app(store)) as api:
        # Add ridge-shell from trailworks ($89)
        r1 = api.post(
            "/api/cart",
            json={"listing_id": "trailworks-direct:ridge-shell", "quantity": 1},
        )
        assert r1.status_code == 200
        assert r1.json()["total"] == 89.0

        # Add same product_id ridge-shell from summit ($94)
        r2 = api.post(
            "/api/cart",
            json={"listing_id": "summit-outfitters:ridge-shell", "quantity": 1},
        )
        assert r2.status_code == 200
        assert r2.json()["total"] == 183.0

        cart = api.get("/api/cart").json()
        assert len(cart["items"]) == 2

        by_listing = {item["listing_id"]: item for item in cart["items"]}
        tw_item = by_listing["trailworks-direct:ridge-shell"]
        assert tw_item["product_id"] == "ridge-shell"
        assert tw_item["store_id"] == "trailworks-direct"
        assert tw_item["unit_price"] == 89.0
        assert tw_item["quantity"] == 1

        summit_item = by_listing["summit-outfitters:ridge-shell"]
        assert summit_item["product_id"] == "ridge-shell"
        assert summit_item["store_id"] == "summit-outfitters"
        assert summit_item["unit_price"] == 94.0
        assert summit_item["quantity"] == 1

        # Insufficient stock check (summit stock is 3, 1 already in cart, adding 3 more fails)
        assert (
            api.post(
                "/api/cart",
                json={"listing_id": "summit-outfitters:ridge-shell", "quantity": 3},
            ).status_code
            == 409
        )

        # Reset clears cart
        assert api.post("/internal/reset", json={}).status_code == 200
        assert api.get("/api/cart").json()["items"] == []


def test_scoring_expected_outcome_valid_listing_ids():
    # Only valid_listing_ids on product outcome is valid
    o1 = ExpectedOutcome(
        kind="product", valid_listing_ids=["trailworks-direct:ridge-shell"]
    )
    assert o1.valid_listing_ids == ["trailworks-direct:ridge-shell"]
    assert o1.valid_product_ids == []

    # Both valid_product_ids and valid_listing_ids on product outcome is valid
    o2 = ExpectedOutcome(
        kind="product",
        valid_product_ids=["ridge-shell"],
        valid_listing_ids=["trailworks-direct:ridge-shell"],
    )
    assert o2.valid_listing_ids == ["trailworks-direct:ridge-shell"]
    assert o2.valid_product_ids == ["ridge-shell"]

    # Product outcome with neither raises ValidationError
    with pytest.raises(ValidationError, match="product outcome needs"):
        ExpectedOutcome(kind="product")

    # Non-product outcome cannot list valid_listing_ids
    with pytest.raises(ValidationError, match="non-product outcome cannot list"):
        ExpectedOutcome(
            kind="no_valid_product",
            valid_listing_ids=["trailworks-direct:ridge-shell"],
        )

    # Clarification cannot list valid_listing_ids
    with pytest.raises(ValidationError, match="non-product outcome cannot list"):
        ExpectedOutcome(
            kind="clarification",
            question_contains="What size?",
            valid_listing_ids=["trailworks-direct:ridge-shell"],
        )

    # Valid non-product outcomes still work
    assert ExpectedOutcome(kind="no_valid_product").kind == "no_valid_product"
    assert (
        ExpectedOutcome(kind="clarification", question_contains="size").question_contains
        == "size"
    )


def test_multi_store_tasks_load():
    ingest, tasks = load_multi_store_examples()
    assert "multistore_cheapest_waterproof_shell" in tasks
    assert "multistore_cheapest_size9_waterproof_hiker" in tasks

    shell_task = tasks["multistore_cheapest_waterproof_shell"]
    assert shell_task.catalog_version == "stores-v1"
    assert shell_task.expected.valid_listing_ids == ["trailworks-direct:ridge-shell"]

    hiker_task = tasks["multistore_cheapest_size9_waterproof_hiker"]
    assert hiker_task.catalog_version == "stores-v1"
    assert hiker_task.expected.valid_listing_ids == ["headwater-supply:tarn-fell"]


def test_listing_aware_scoring_accepts_cheapest_store_only():
    from shopping_agent.eval.scoring import score
    from shopping_agent.interfaces import AgentOutput

    ingest, tasks = load_multi_store_examples()
    task = tasks["multistore_cheapest_waterproof_shell"]
    store = MultiStore(ingest, tasks)
    store.reset(task.task_id)
    store.add_to_cart(listing_id="trailworks-direct:ridge-shell", quantity=1)
    snapshot = store.snapshot()

    ok, _, _ = score(
        task,
        AgentOutput(
            selected_product_ids=["ridge-shell"],
            selected_listing_ids=["trailworks-direct:ridge-shell"],
            response_text="Chose Trailworks listing.",
            termination_reason="completed",
        ),
        snapshot,
    )
    assert ok

    # Same product_id from a more expensive store must fail listing scoring.
    store.reset(task.task_id)
    store.add_to_cart(listing_id="summit-outfitters:ridge-shell", quantity=1)
    bad, _, _ = score(
        task,
        AgentOutput(
            selected_product_ids=["ridge-shell"],
            selected_listing_ids=["summit-outfitters:ridge-shell"],
            response_text="Chose Summit listing.",
            termination_reason="completed",
        ),
        store.snapshot(),
    )
    assert not bad


def test_listing_scoped_mutation_isolation():
    ingest = load_ingest(INGEST_PATH)
    task = TaskDefinition(
        task_id="test_listing_mutation",
        version="stores-v1",
        catalog_version="stores-v1",
        difficulty="easy",
        request=ShoppingRequest(original_text="test request"),
        ranking_rule="lowest_price",
        expected=ExpectedOutcome(
            kind="product",
            valid_listing_ids=["trailworks-direct:ridge-shell"],
        ),
        mutations=[
            Mutation(
                after_observations=1,
                product_id="ridge-shell",
                listing_id="trailworks-direct:ridge-shell",
                price=109.0,
            )
        ],
    )
    store = MultiStore(ingest, {task.task_id: task})
    with TestClient(create_app(store)) as api:
        api.post("/internal/reset", json={"task_id": "test_listing_mutation"})

        # Initial price: trailworks is $89, summit is $94
        assert (
            api.get("/api/listings/trailworks-direct:ridge-shell").json()["price"]
            == 89.0
        )
        # 1 observation has now elapsed, next call triggers mutation on trailworks listing only
        assert (
            api.get("/api/listings/trailworks-direct:ridge-shell").json()["price"]
            == 109.0
        )
        # Summit listing must be UNTOUCHED at $94
        assert (
            api.get("/api/listings/summit-outfitters:ridge-shell").json()["price"]
            == 94.0
        )
