"""Call limits and cooperative deadlines; the runner also enforces a process deadline."""

from time import monotonic
from typing import Callable

from shopping_agent.contracts import CartSelection, Contract, SearchInput
from shopping_agent.interfaces import ShoppingTools


class ToolTrace(Contract):
    sequence: int
    name: str
    inputs: dict
    observation: dict | None = None
    error: str | None = None
    duration_seconds: float = 0


class BudgetExceeded(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class BudgetedTools:
    def __init__(
        self,
        tools: ShoppingTools,
        max_calls: int = 20,
        seconds: float = 60,
        clock: Callable = monotonic,
        on_trace: Callable | None = None,
    ):
        if max_calls < 1 or seconds <= 0:
            raise ValueError("budgets must be positive")

        self._tools = tools
        self._clock = clock
        self._on_trace = on_trace
        self.max_calls = max_calls
        self.deadline = clock() + seconds
        self.trace: list[ToolTrace] = []

    def _call(self, name: str, inputs):
        if self._clock() >= self.deadline:
            raise BudgetExceeded("timeout")

        if len(self.trace) >= self.max_calls:
            raise BudgetExceeded("max_tool_calls_exceeded")

        if hasattr(inputs, "model_dump"):
            serialized_inputs = inputs.model_dump(mode="json")
        elif inputs is not None:
            serialized_inputs = {"product_id": inputs}
        else:
            serialized_inputs = {}

        event = ToolTrace(
            sequence=len(self.trace) + 1,
            name=name,
            inputs=serialized_inputs,
        )
        self.trace.append(event)

        if self._on_trace:
            self._on_trace(event)  # Persist attempted calls even if the operation blocks.

        start = self._clock()

        try:
            method = getattr(self._tools, name)
            result = method() if inputs is None else method(inputs)
            if hasattr(result, "model_dump"):
                event.observation = result.model_dump(mode="json")
            elif isinstance(result, list):
                event.observation = [
                    item.model_dump(mode="json") if hasattr(item, "model_dump") else item
                    for item in result
                ]
            else:
                event.observation = result

        except Exception as exc:
            event.error = f"{type(exc).__name__}: {exc}"
            raise

        finally:
            event.duration_seconds = self._clock() - start

            if self._on_trace:
                self._on_trace(event)

        if self._clock() >= self.deadline:
            raise BudgetExceeded("timeout")

        return result

    def search(self, inputs: SearchInput):
        return self._call("search", inputs)

    def get_listing(
        self,
        product_id: str | None = None,
        *,
        store_id: str | None = None,
        listing_id: str | None = None,
    ):
        if self._clock() >= self.deadline:
            raise BudgetExceeded("timeout")
        if len(self.trace) >= self.max_calls:
            raise BudgetExceeded("max_tool_calls_exceeded")

        serialized = {
            "product_id": product_id,
            "store_id": store_id,
            "listing_id": listing_id,
        }
        event = ToolTrace(sequence=len(self.trace) + 1, name="get_listing", inputs=serialized)
        self.trace.append(event)
        if self._on_trace:
            self._on_trace(event)
        start = self._clock()
        try:
            result = self._tools.get_listing(
                product_id, store_id=store_id, listing_id=listing_id
            )
            event.observation = result.model_dump(mode="json")
        except Exception as exc:
            event.error = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            event.duration_seconds = self._clock() - start
            if self._on_trace:
                self._on_trace(event)
        if self._clock() >= self.deadline:
            raise BudgetExceeded("timeout")
        return result

    def add_to_cart(self, selection: CartSelection):
        return self._call("add_to_cart", selection)

    def inspect_cart(self):
        return self._call("inspect_cart", None)

    def list_stores(self):
        return self._call("list_stores", None)
