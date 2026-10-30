from fastapi.testclient import TestClient

from server.app import create_app
from server.state import Store, load_examples


def client():
    catalog, tasks = load_examples()
    return TestClient(create_app(Store(catalog, tasks)))


def test_search_detail_reviews_and_sponsored_order():
    with client() as api:
        items = api.get("/api/products", params={"q": "jacket"}).json()

        assert [item["product_id"] for item in items] == [
            "city-windbreaker", "ridge-shell", "ridge-shell-reseller", "river-shell",
            "summit-shell",
        ]

        assert items[0]["sponsored"]
        assert items[1]["rating"] == 4.5
        assert api.get("/api/products/ridge-shell/reviews").json()[0]["rating"] == 5
        assert api.get("/api/products/does-not-exist").status_code == 404


def test_cart_checks_live_stock_and_reset():
    with client() as api:
        assert api.post("/api/cart", json={"product_id": "river-shell", "quantity": 2}).status_code == 409

        cart = api.post("/api/cart", json={"product_id": "river-shell", "quantity": 1}).json()

        assert cart["total"] == 79
        assert api.post("/api/cart", json={"product_id": "river-shell", "quantity": 1}).status_code == 409

        assert api.post("/internal/reset", json={}).status_code == 200
        assert api.get("/api/cart").json()["items"] == []


def test_mutation_occurs_after_one_observation_and_reset_replays_it():
    with client() as api:
        api.post("/internal/reset", json={"task_id": "price_change"})

        assert api.get("/api/products/ridge-shell").json()["price"] == 89
        assert api.get("/api/products/ridge-shell").json()["price"] == 109

        assert api.post("/api/cart", json={"product_id": "ridge-shell", "quantity": 1}).json()["total"] == 109

        api.post("/internal/reset", json={"task_id": "price_change"})
        assert api.get("/api/products/ridge-shell").json()["price"] == 89


def test_invalid_inputs_and_oracle_state():
    with client() as api:
        assert api.post("/internal/reset", json={"task_id": "missing"}).status_code == 404
        assert api.get("/api/products", params={"limit": 0}).status_code == 422
        assert api.post("/api/cart", json={"product_id": "ridge-shell", "quantity": 0}).status_code == 422

        assert api.get("/internal/state").json()["catalog_version"] == "catalog-v2"


def test_empty_search_and_stock_mutation_reject_stale_cart():
    with client() as api:
        api.post("/internal/reset", json={"task_id": "stock_change"})

        assert api.get("/api/products", params={"q": "unfindable"}).json() == []
        assert api.post("/api/cart", json={"product_id": "river-shell", "quantity": 1}).status_code == 409
        assert api.get("/api/products/river-shell").json()["stock"] == 0

        api.post("/internal/reset", json={"task_id": "stock_change"})
        assert api.get("/api/products/river-shell").json()["stock"] == 1
