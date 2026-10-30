import json

import pytest
from pydantic import ValidationError

from shopping_agent.contracts import CatalogExample, Constraint, ExpectedOutcome, Mutation, Product
from shopping_agent.example_checks import matches
from server.state import load_examples


def test_examples_load_and_reference_a_known_catalog():
    catalog, tasks = load_examples()

    assert len(catalog.products) == 20
    assert set(tasks) == {
        "cheapest_waterproof_jacket", "no_waterproof_under_50", "price_change",
        "clarify_jacket_size", "stock_change",
    }

    assert all(task.catalog_version == catalog.version for task in tasks.values())


def test_catalog_rejects_duplicate_ids():
    catalog, _ = load_examples()

    with pytest.raises(ValidationError, match="unique"):
        CatalogExample(version="v1", products=[catalog.products[0], catalog.products[0]])


@pytest.mark.parametrize("price", [-1, float("inf"), 12.345])
def test_product_rejects_invalid_prices(price):
    catalog, _ = load_examples()

    with pytest.raises(ValidationError):
        Product.model_validate({**catalog.products[0].model_dump(), "price": price})


def test_product_accepts_finite_fractional_cents():
    catalog, _ = load_examples()
    product = Product.model_validate({**catalog.products[0].model_dump(), "price": 0.29})

    assert product.price == 0.29


def test_mutation_and_expected_outcome_require_meaningful_fields():
    with pytest.raises(ValidationError):
        Mutation(after_observations=1, product_id="ridge-shell")

    with pytest.raises(ValidationError):
        ExpectedOutcome(kind="product")


def test_bool_is_not_numeric_and_missing_attribute_is_not_a_match():
    catalog, _ = load_examples()
    product = catalog.products[0]

    assert matches(product, Constraint(attribute="price", operator="lte", value=100))
    assert not matches(product, Constraint(attribute="waterproof", operator="eq", value=1))
    assert not matches(product, Constraint(attribute="fictional_feature", operator="eq", value=True))


def test_loader_rejects_wrong_expected_answer(tmp_path):
    catalog, tasks = load_examples()
    catalog_path = tmp_path / "catalog.json"
    tasks_path = tmp_path / "tasks"
    tasks_path.mkdir()
    catalog_path.write_text(catalog.model_dump_json())
    task = tasks["cheapest_waterproof_jacket"].model_dump(mode="json")
    task["expected"]["valid_product_ids"] = ["city-windbreaker"]
    (tasks_path / "wrong.json").write_text(json.dumps(task))

    with pytest.raises(ValueError, match="computed"):
        load_examples(catalog_path, tasks_path)
