"""Public agent/tool boundary. No task expectations or environment controls."""
from typing import Literal, Protocol

from pydantic import Field

from shopping_agent.contracts import (
    Attribute, CartSelection, Contract, EvidenceItem, ProductObservation,
    SearchInput, SearchResult, ShoppingRequest,
)

Termination = Literal[
    "completed", "no_valid_product", "clarification_needed",
    "max_tool_calls_exceeded", "timeout", "unrecoverable_failure",
]


class AgentInput(Contract):
    request: ShoppingRequest
    ranking_rule: Literal[
        "lowest_price", "highest_rating", "highest_rating_then_reviews", "none"
    ] | None = None


class Claim(Contract):
    claim_id: str
    product_id: str
    field: str
    value: Attribute


class AgentOutput(Contract):
    selected_product_ids: list[str] = Field(default_factory=list)
    response_text: str
    claims: list[Claim] = Field(default_factory=list)
    evidence: list[EvidenceItem] = Field(default_factory=list)
    termination_reason: Termination
    diagnostics: dict = Field(default_factory=dict)


class CartItemObservation(CartSelection):
    unit_price: float
    line_total: float
    in_stock: bool


class CartObservation(Contract):
    items: list[CartItemObservation]
    total: float
    currency: str = "USD"
    source_url: str
    observed_at: str


class ShoppingTools(Protocol):
    def search(self, inputs: SearchInput) -> SearchResult: ...
    def get_listing(self, product_id: str) -> ProductObservation: ...
    def add_to_cart(self, selection: CartSelection) -> CartObservation: ...
    def inspect_cart(self) -> CartObservation: ...


class Agent(Protocol):
    def run(self, inputs: AgentInput, tools: ShoppingTools) -> AgentOutput: ...
