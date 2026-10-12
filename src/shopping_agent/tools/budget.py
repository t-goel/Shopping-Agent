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
    def __init__(self, tools: ShoppingTools, max_calls: int = 10, seconds: float = 60,
                 clock: Callable = monotonic, on_trace: Callable | None = None):
        if max_calls < 1 or seconds <= 0:
            raise ValueError("budgets must be positive")
        self._tools, self._clock, self._on_trace = tools, clock, on_trace
        self.max_calls = max_calls
        self.deadline = clock() + seconds
        self.trace: list[ToolTrace] = []

    def _call(self, name, inputs):
        if self._clock() >= self.deadline:
            raise BudgetExceeded("timeout")
        if len(self.trace) >= self.max_calls:
            raise BudgetExceeded("max_tool_calls_exceeded")
        event = ToolTrace(sequence=len(self.trace) + 1, name=name,
                          inputs=inputs.model_dump(mode="json") if hasattr(inputs, "model_dump")
                          else {"product_id": inputs} if inputs is not None else {})
        self.trace.append(event)
        if self._on_trace:
            self._on_trace(event)  # Persist attempted calls even if the operation blocks.
        start = self._clock()
        try:
            method = getattr(self._tools, name)
            result = method() if inputs is None else method(inputs)
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

    def search(self, inputs: SearchInput):
        return self._call("search", inputs)

    def get_listing(self, product_id: str):
        return self._call("get_listing", product_id)

    def add_to_cart(self, selection: CartSelection):
        return self._call("add_to_cart", selection)

    def inspect_cart(self):
        return self._call("inspect_cart", None)
