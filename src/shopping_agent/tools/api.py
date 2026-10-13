"""Allowlisted public HTTP operations; transport may be live HTTP or ASGI in tests."""

from datetime import datetime, timezone
from urllib.parse import quote

import httpx

from shopping_agent.contracts import (
    CartSelection,
    Product,
    ProductObservation,
    SearchInput,
    SearchResult,
)
from shopping_agent.interfaces import CartObservation


class ToolError(Exception):
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class CatalogAPI:
    def __init__(self, client: httpx.Client):
        self._client = client

    def _request(self, method: str, path: str, **kwargs):
        try:
            response = self._client.request(method, path, **kwargs)
            response.raise_for_status()
            return response

        except httpx.HTTPStatusError as exc:
            raise ToolError(
                f"HTTP {exc.response.status_code}: {exc.response.text}",
                exc.response.status_code,
            ) from exc

        except httpx.HTTPError as exc:
            raise ToolError(str(exc)) from exc

    @staticmethod
    def _observation(data: dict) -> ProductObservation:
        product = Product.model_validate({key: data[key] for key in Product.model_fields if key in data})
        return ProductObservation(
            product=product,
            source_url=data["source_url"],
            observed_at=data["observed_at"],
            catalog_version=data["catalog_version"],
        )

    def search(self, inputs: SearchInput) -> SearchResult:
        response = self._request(
            "GET",
            "/api/products",
            params={"q": inputs.query, "limit": inputs.max_results},
        )
        return SearchResult(
            items=[self._observation(row) for row in response.json()],
            query=inputs.query,
        )

    def get_listing(self, product_id: str) -> ProductObservation:
        response = self._request("GET", f"/api/products/{quote(product_id, safe='')}")
        return self._observation(response.json())

    def _cart(self, response: httpx.Response) -> CartObservation:
        return CartObservation(
            **response.json(),
            source_url=str(self._client.base_url.join("/api/cart")),
            observed_at=datetime.now(timezone.utc).isoformat(),
        )

    def add_to_cart(self, selection: CartSelection) -> CartObservation:
        return self._cart(self._request("POST", "/api/cart", json=selection.model_dump()))

    def inspect_cart(self) -> CartObservation:
        return self._cart(self._request("GET", "/api/cart"))
