"""Tests for multi-store multi-store runtime, ingest projection, and contracts."""

from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from server.app import create_app
from server.multi_store import MultiStore, load_multi_store_examples
from server.state import StoreError
from shopping_agent.contracts import (
    CartSelection,
    ExpectedOutcome,
    Mutation,
    ShoppingRequest,
    TaskDefinition,
)
from shopping_agent.ingest import (
    load_ingest,
    load_partition,
    merge_partition_with_catalog,
    project_compat,
    project_multi,
)
from shopping_agent.tools.api import CatalogAPI
from shopping_agent.eval.scoring import score
from shopping_agent.interfaces import AgentOutput
from shopping_agent.contracts import CatalogExample

ROOT = Path(__file__).resolve().parents[1]
INGEST_PATH = ROOT / "mock-store/server/examples/ingest.example.json"


def test_ingest_load_and_canonical_compat_prices():
    ingest = load_ingest(INGEST_PATH)
    assert len(ingest.stores) == 5
    assert len(ingest.products) == 6
    assert len(ingest.assortment) == 10

    compat = project_compat(ingest)
    assert compat["mode"] == "compat"
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
    assert multi["mode"] == "multi-store"
    assert multi["meta"]["listing_count"] == 10
    assert len(multi["listings"]) == 10


def test_store_scoped_search_and_validation():
    ingest, tasks = load_multi_store_examples()
    store = MultiStore(ingest, tasks)

    # Direct store search
    tw_results = store.search("waterproof", store_id="trailworks-direct")
    assert any(p.product_id == "ridge-shell" and p.price == 89.0 for p in tw_results)

    summit_results = store.search("waterproof", store_id="summit-outfitters")
    assert any(p.product_id == "ridge-shell" and p.price == 94.0 for p in summit_results)

    # Missing or unknown store_id raises StoreError 400
    with pytest.raises(StoreError) as exc_missing:
        store.search("waterproof", store_id="")
    assert exc_missing.value.status == 400

    with pytest.raises(StoreError) as exc_unknown:
        store.search("waterproof", store_id="nonexistent-store")
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

        # Shared /api/products still works when store_id is supplied (CatalogAPI path).
        via_shared = api.get(
            "/api/products",
            params={"q": "waterproof", "store_id": "trailworks-direct"},
        ).json()
        assert any(
            item["product_id"] == "ridge-shell" and item["price"] == 89.0
            for item in via_shared
        )

        # Missing store_id => 400 (no federated search)
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
    assert len(tasks) >= 4
    assert "multistore_cheapest_waterproof_shell" in tasks
    assert "multistore_cheapest_size9_waterproof_hiker" in tasks
    assert "multistore_cheapest_harbor_backpack" in tasks
    assert "multistore_avoid_clearance_reseller_shell" in tasks

    shell_task = tasks["multistore_cheapest_waterproof_shell"]
    assert shell_task.expected.valid_listing_ids == ["trailworks-direct:ridge-shell"]

    hiker_task = tasks["multistore_cheapest_size9_waterproof_hiker"]
    assert hiker_task.expected.valid_listing_ids == ["headwater-supply:tarn-fell"]


def test_rules_agent_passes_cheapest_shell_on_multi_store_runner():
    from shopping_agent.eval.runner import run_trial

    ingest, tasks = load_multi_store_examples()
    task = tasks["multistore_cheapest_waterproof_shell"]
    result = run_trial(ingest, task, trial_number=1, max_calls=40, seconds=30)
    assert result.is_successful, (result.termination_reason, result.error, result.response_text)
    assert result.selected_listing_ids == ["trailworks-direct:ridge-shell"]


def test_partition_loader_accepts_blurb_and_role():
    partition = load_partition(ROOT / "mock-store/server/examples/stores-partition.json")
    assert partition.stores[0].notes  # blurb aliased to notes
    assert any(row.role == "overlap" for row in partition.assortment)
    catalog = CatalogExample.model_validate_json(
        (ROOT / "mock-store/server/examples/catalog.json").read_text(encoding="utf-8")
    )
    merged = merge_partition_with_catalog(partition, catalog)
    assert merged.catalog_bootstrap == "catalog"
    assert len(merged.assortment) == len(partition.assortment)


def test_listing_lookup_and_list_stores_via_api():
    ingest, tasks = load_multi_store_examples()
    store = MultiStore(ingest, tasks)
    with TestClient(create_app(store)) as client:
        api = CatalogAPI(client)
        stores = api.list_stores()
        assert {s.store_id for s in stores} >= {"trailworks-direct", "summit-outfitters"}

        by_pair = api.get_listing("ridge-shell", store_id="summit-outfitters")
        assert by_pair.store_id == "summit-outfitters"
        assert by_pair.listing_id == "summit-outfitters:ridge-shell"
        assert by_pair.product.price == 94.0

        by_listing = api.get_listing(listing_id="trailworks-direct:ridge-shell")
        assert by_listing.listing_id == "trailworks-direct:ridge-shell"
        assert by_listing.product.price == 89.0


def test_multi_store_no_valid_product_scoring_does_not_crash():
    ingest, tasks = load_multi_store_examples()
    task = tasks["multistore_cheapest_waterproof_shell"].model_copy(deep=True)
    task.expected.kind = "no_valid_product"
    task.expected.valid_product_ids = []
    task.expected.valid_listing_ids = []
    # Impossible constraints so candidates empty.
    task.request.constraints[0].value = "spaceships"
    store = MultiStore(ingest, {task.task_id: task})
    store.reset(task.task_id)
    ok, _, _ = score(
        task,
        AgentOutput(
            response_text="Nothing matched.",
            termination_reason="no_valid_product",
        ),
        store.snapshot(),
    )
    assert ok


def test_add_to_cart_requires_listing_or_store_pair():
    ingest, tasks = load_multi_store_examples()
    store = MultiStore(ingest, tasks)
    with pytest.raises(StoreError) as exc:
        store.add_to_cart(product_id="ridge-shell", quantity=1)
    assert exc.value.status == 422

    with TestClient(create_app(store)) as api:
        assert (
            api.post("/api/cart", json={"product_id": "ridge-shell", "quantity": 1}).status_code
            == 422
        )
        ok = api.post(
            "/api/cart",
            json={
                "product_id": "ridge-shell",
                "store_id": "trailworks-direct",
                "quantity": 1,
            },
        )
        assert ok.status_code == 200
        assert ok.json()["items"][0]["listing_id"] == "trailworks-direct:ridge-shell"


def test_listing_aware_scoring_accepts_cheapest_store_only():
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


def test_add_to_cart_unambiguous_product_id_resolution():
    ingest, tasks = load_multi_store_examples()
    store = MultiStore(ingest, tasks)

    # 'ridge-shell-reseller' exists only in clearance-corner
    cart = store.add_to_cart(product_id="ridge-shell-reseller", quantity=1)
    assert len(cart.items) == 1
    assert cart.items[0].listing_id == "clearance-corner:ridge-shell-reseller"
    assert cart.items[0].store_id == "clearance-corner"

    # Also test via API endpoint
    with TestClient(create_app(store)) as api:
        res = api.post("/api/cart", json={"product_id": "meadow-sling", "quantity": 1})
        assert res.status_code == 200
        items = res.json()["items"]
        assert any(item["listing_id"] == "metrowear:meadow-sling" for item in items)


def test_add_to_cart_ambiguous_product_id_error_message():
    ingest, tasks = load_multi_store_examples()
    store = MultiStore(ingest, tasks)

    # 'ridge-shell' exists in 3 stores: trailworks-direct, summit-outfitters, clearance-corner
    with pytest.raises(StoreError) as exc:
        store.add_to_cart(product_id="ridge-shell", quantity=1)
    assert exc.value.status == 422
    assert "Ambiguous product_id 'ridge-shell'" in str(exc.value)
    assert "trailworks-direct:ridge-shell" in str(exc.value)
    assert "summit-outfitters:ridge-shell" in str(exc.value)
    assert "Specify listing_id or store_id" in str(exc.value)

    # Also test via API endpoint
    with TestClient(create_app(store)) as api:
        res = api.post("/api/cart", json={"product_id": "ridge-shell", "quantity": 1})
        assert res.status_code == 422
        assert "Ambiguous product_id 'ridge-shell'" in res.json()["detail"]


def test_get_listing_unambiguous_and_ambiguous_resolution():
    ingest, tasks = load_multi_store_examples()
    store = MultiStore(ingest, tasks)

    # Unambiguous product id in get_listing
    listing = store.get_listing("meadow-sling")
    assert listing.listing_id == "metrowear:meadow-sling"
    assert listing.store_id == "metrowear"

    # Ambiguous product id in get_listing
    with pytest.raises(StoreError) as exc:
        store.get_listing("ridge-shell")
    assert exc.value.status == 422
    assert "Ambiguous product_id 'ridge-shell'" in str(exc.value)

    with TestClient(create_app(store)) as api:
        res_ok = api.get("/api/listings/meadow-sling")
        assert res_ok.status_code == 200
        assert res_ok.json()["listing_id"] == "metrowear:meadow-sling"

        res_ambig = api.get("/api/listings/ridge-shell")
        assert res_ambig.status_code == 422
        assert "Ambiguous product_id 'ridge-shell'" in res_ambig.json()["detail"]


def test_catalog_api_listing_id_resolution():
    ingest, tasks = load_multi_store_examples()
    store = MultiStore(ingest, tasks)
    with TestClient(create_app(store)) as client:
        api = CatalogAPI(client)

        # Pass listing_id in product_id argument
        obs = api.get_listing("trailworks-direct:ridge-shell")
        assert obs.listing_id == "trailworks-direct:ridge-shell"
        assert obs.store_id == "trailworks-direct"

        # Pass bare product_id in listing_id argument with store_id
        obs2 = api.get_listing(listing_id="ridge-shell", store_id="summit-outfitters")
        assert obs2.listing_id == "summit-outfitters:ridge-shell"
        assert obs2.store_id == "summit-outfitters"

        # Pass unambiguous product_id to get_listing
        obs3 = api.get_listing("meadow-sling")
        assert obs3.product.product_id == "meadow-sling"

        # Add to cart with listing_id in product_id field
        cart = api.add_to_cart(CartSelection(product_id="trailworks-direct:ridge-shell", quantity=1))
        assert len(cart.items) == 1
        assert cart.items[0].listing_id == "trailworks-direct:ridge-shell"


def test_api_product_endpoint_accepts_listing_id():
    ingest, tasks = load_multi_store_examples()
    store = MultiStore(ingest, tasks)
    with TestClient(create_app(store)) as api:
        res = api.get("/api/products/trailworks-direct:ridge-shell")
        assert res.status_code == 200
        data = res.json()
        assert data["product_id"] == "ridge-shell"
        assert data["store_id"] == "trailworks-direct"
        assert data["listing_id"] == "trailworks-direct:ridge-shell"

