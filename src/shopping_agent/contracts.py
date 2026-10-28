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
    question_contains: str | None = None

    @model_validator(mode="after")
    def consistent_outcome(self):
        if self.kind == "product" and not self.valid_product_ids:
            raise ValueError("product outcome needs at least one valid product")

        if self.kind != "product" and self.valid_product_ids:
            raise ValueError("non-product outcome cannot list valid products")

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

    @model_validator(mode="after")
    def clarification_matches_request(self):
        planted = bool(self.request.clarification_needed)
        wants_clarify = self.expected.kind == "clarification"

        if self.agent_surface == "nl":
            # Surface B: never plant the question string; scoring uses question_contains.
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
