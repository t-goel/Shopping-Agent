"""Versioned example, store, and evaluation contracts shared across the project."""

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from math import isfinite
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


Attribute = str | int | float | bool


class Operator(StrEnum):
    EQ = "eq"
    GTE = "gte"
    LTE = "lte"
    CONTAINS = "contains"


class Constraint(Contract):
    attribute: str = Field(min_length=1)
    operator: Operator
    value: Attribute
    hard: bool = True


class ShoppingRequest(Contract):
    original_text: str = Field(min_length=1)
    constraints: list[Constraint] = Field(default_factory=list)
    preferences: list[str] = Field(default_factory=list)
    clarification_needed: str | None = None


class Review(Contract):
    review_id: str = Field(min_length=1)
    rating: int = Field(ge=1, le=5)
    text: str


class StoreRecord(Contract):
    store_id: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    name: str = Field(min_length=1)
    brand_seller: str = Field(min_length=1)
    notes: str | None = None


class Product(Contract):
    product_id: str = Field(pattern=r"^[a-z0-9_-]+$")
    title: str = Field(min_length=1)
    description: str
    category: str = Field(min_length=1)
    price: float = Field(ge=0)
    currency: Literal["USD"] = "USD"
    stock: int = Field(ge=0)
    seller: str = Field(min_length=1)
    attributes: dict[str, Attribute]
    reviews: list[Review] = Field(default_factory=list)
    sponsored: bool = False
    image_url: HttpUrl | None = None

    @model_validator(mode="after")
    def validate_price(self):
        if not isfinite(self.price) or Decimal(str(self.price)) * 100 % 1 != 0:
            raise ValueError("price must be a finite number of whole cents")
        return self


class CatalogExample(Contract):
    version: str = Field(min_length=1)
    products: list[Product] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_ids(self):
        ids = [product.product_id for product in self.products]

        if len(ids) != len(set(ids)):
            raise ValueError("product IDs must be unique")

        return self


class Mutation(Contract):
    # Applied after N read observations and before the next read or cart write.
    after_observations: int = Field(ge=1)
    product_id: str
    price: float | None = Field(default=None, ge=0)
    stock: int | None = Field(default=None, ge=0)
    store_id: str | None = None
    listing_id: str | None = None

    @model_validator(mode="after")
    def changed_field(self):
        if self.price is None and self.stock is None:
            raise ValueError("mutation must change price or stock")

        if self.price is not None and (
            not isfinite(self.price) or Decimal(str(self.price)) * 100 % 1 != 0
        ):
            raise ValueError("price must be a finite number of whole cents")

        return self


class ExpectedOutcome(Contract):
    kind: Literal["product", "no_valid_product", "clarification"]
    valid_product_ids: list[str] = Field(default_factory=list)
    valid_listing_ids: list[str] = Field(default_factory=list)
    question_contains: str | None = None

    @model_validator(mode="after")
    def consistent_outcome(self):
        if self.kind == "product":
            if not self.valid_product_ids and not self.valid_listing_ids:
                raise ValueError("product outcome needs at least one valid product or listing")
        else:
            if self.valid_product_ids:
                raise ValueError("non-product outcome cannot list valid products")
            if self.valid_listing_ids:
                raise ValueError("non-product outcome cannot list valid listings")

        if self.kind == "clarification" and not self.question_contains:
            raise ValueError("clarification outcome needs question_contains")

        return self


class TaskDefinition(Contract):
    task_id: str = Field(pattern=r"^[a-z0-9_-]+$")
    version: str = Field(min_length=1)
    catalog_version: str = Field(min_length=1)
    difficulty: Literal["easy", "medium", "hard"]
    agent_surface: Literal["structured", "nl"] = "structured"
    request: ShoppingRequest
    ranking_rule: Literal[
        "lowest_price", "highest_rating", "highest_rating_then_reviews", "none"
    ]
    expected: ExpectedOutcome
    mutations: list[Mutation] = Field(default_factory=list)
    notes: str | None = None

    @model_validator(mode="after")
    def clarification_matches_request(self):
        planted = bool(self.request.clarification_needed)
        wants_clarify = self.expected.kind == "clarification"

        if self.agent_surface == "nl":
            # NL surface: never plant the question string; scoring uses question_contains.
            if planted:
                raise ValueError("nl surface must not plant clarification_needed")
            if wants_clarify and not self.expected.question_contains:
                raise ValueError("nl clarification needs question_contains")
            return self

        if wants_clarify != planted:
            raise ValueError("clarification outcome and request must agree")

        return self


class SearchInput(Contract):
    query: str = Field(min_length=1, max_length=200)
    max_results: int = Field(default=20, ge=1, le=50)
    store_id: str | None = None


class ProductObservation(Contract):
    product: Product
    source_url: str
    observed_at: datetime
    catalog_version: str


class SearchResult(Contract):
    items: list[ProductObservation]
    query: str


class EvidenceItem(Contract):
    claim_id: str
    product_id: str
    field: str
    claimed_value: Attribute
    observed_value: Attribute | None
    status: Literal["supports", "contradicts", "unknown"]
    source_url: str
    observed_at: datetime


class CartSelection(Contract):
    product_id: str
    quantity: int = Field(ge=1)
    store_id: str | None = None
    listing_id: str | None = None


class TrialResult(Contract):
    task_id: str
    task_version: str
    catalog_version: str
    agent_name: str
    model_id: str | None
    prompt_version: str | None
    trial_number: int = Field(ge=1)
    mode: Literal["api", "browser"]
    selected_product_ids: list[str]
    selected_listing_ids: list[str] = Field(default_factory=list)
    response_text: str
    cart_items: list[CartSelection] = Field(default_factory=list)
    evidence: list[EvidenceItem] = Field(default_factory=list)
    constraints_satisfied: int = Field(ge=0)
    total_constraints: int = Field(ge=0)
    tool_calls: int = Field(ge=0)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    cost_usd: float | None = Field(default=None, ge=0)
    duration_seconds: float = Field(ge=0)
    termination_reason: Literal[
        "completed", "no_valid_product", "clarification_needed",
        "max_tool_calls_exceeded", "timeout", "unrecoverable_failure",
    ]
    is_successful: bool
    difficulty: Literal["easy", "medium", "hard"] | None = None
    expected_kind: Literal["product", "no_valid_product", "clarification"] | None = None
    claims: list[dict] = Field(default_factory=list)
    tool_trace: list[dict] = Field(default_factory=list)
    final_state: dict | None = None
    error: str | None = None
    run_metadata: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def bounded_satisfaction(self):
        if self.constraints_satisfied > self.total_constraints:
            raise ValueError("satisfied constraints cannot exceed total constraints")

        return self


class IngestProvenance(Contract):
    method: Literal["synthetic", "manual_capture", "partner_feed", "official_api"]
    retailer_hint: str | None = None
    source_url: str | None = None
    captured_at: str | datetime | None = None
    notes: str | None = None


class IngestProduct(Contract):
    product_id: str = Field(pattern=r"^[a-z0-9_-]+$")
    title: str = Field(min_length=1)
    description: str = ""
    category: str = Field(min_length=1)
    currency: Literal["USD"] = "USD"
    canonical_store_id: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    seller_default: str = Field(min_length=1)
    attributes: dict[str, Attribute] = Field(default_factory=dict)
    reviews: list[Review] = Field(default_factory=list)
    image_url: HttpUrl | None = None
    provenance: IngestProvenance | None = None


class AssortmentRow(Contract):
    listing_id: str = Field(pattern=r"^[a-z0-9-]+:[a-z0-9_-]+$")
    store_id: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    product_id: str = Field(pattern=r"^[a-z0-9_-]+$")
    price: float = Field(ge=0)
    stock: int = Field(ge=0)
    sponsored: bool = False

    @model_validator(mode="after")
    def validate_price_and_id(self):
        if not isfinite(self.price) or Decimal(str(self.price)) * 100 % 1 != 0:
            raise ValueError("price must be a finite number of whole cents")
        expected = listing_id_for(self.store_id, self.product_id)
        if self.listing_id != expected:
            raise ValueError(f"listing_id {self.listing_id!r} != {expected!r}")
        return self


def listing_id_for(store_id: str, product_id: str) -> str:
    """Canonical listing key: `{store_id}:{product_id}`."""
    return f"{store_id}:{product_id}"


def resolve_mutation_rows(
    mutation: Mutation, listings: dict[str, AssortmentRow]
) -> list[AssortmentRow]:
    """Pick assortment rows a mutation should change (listing-, store-, or product-scoped)."""
    if mutation.listing_id:
        row = listings.get(mutation.listing_id)
        return [row] if row is not None else []
    if mutation.store_id:
        row = listings.get(listing_id_for(mutation.store_id, mutation.product_id))
        return [row] if row is not None else []
    return [row for row in listings.values() if row.product_id == mutation.product_id]


class IngestCatalog(Contract):
    ingest_version: Literal["ingest-v1"] = "ingest-v1"
    notes: str | None = None
    stores: list[StoreRecord] = Field(min_length=1)
    products: list[IngestProduct] = Field(min_length=1)
    assortment: list[AssortmentRow] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_relationships(self):
        store_ids = {s.store_id for s in self.stores}
        product_ids = {p.product_id for p in self.products}
        seen: set[tuple[str, str]] = set()
        for row in self.assortment:
            key = (row.store_id, row.product_id)
            if key in seen:
                raise ValueError(f"duplicate assortment row {key}")
            seen.add(key)
            if row.store_id not in store_ids:
                raise ValueError(f"unknown store_id {row.store_id}")
            if row.product_id not in product_ids:
                raise ValueError(f"unknown product_id {row.product_id}")
        for product in self.products:
            canonical = product.canonical_store_id
            if not canonical:
                raise ValueError(f"{product.product_id}: canonical_store_id is required")
            if canonical not in store_ids:
                raise ValueError(
                    f"{product.product_id}: unknown canonical_store_id {canonical!r}"
                )
            if (canonical, product.product_id) not in seen:
                raise ValueError(
                    f"{product.product_id}: no assortment row for canonical_store_id {canonical!r}"
                )
        return self
