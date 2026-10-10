# Mock shopping store

This is a local, resettable storefront for developing and testing shopping agents. It is **not** a real merchant and cannot take payments. Run it only on localhost; the control endpoints expose task answers and mutable ground-truth state.

## Start

From the repository root, install Python packages once with `py -m pip install -r requirements.txt`, then start both servers and open the storefront with `py run.py`. The React app uses the same FastAPI catalog through Vite's development proxy. Visit `http://127.0.0.1:8000/docs` for the FastAPI route explorer. See the root README for Windows setup.

## Examples and task contracts

`server/examples/catalog.json` is the versioned product example. `../data/tasks/*.json` are example task definitions. All products, reviews, task constraints, expected answers, catalog references, and scheduled changes are synthetic. These five examples illustrate formats and edge cases, **not the team's final course benchmark**. The final task suite must be authored and reviewed by the team as required by `project-guidelines.md`.

The shared Pydantic contracts live in `../src/shopping_agent/contracts.py`. Bad examples and mismatched expected winners fail at startup. Authoring checks in `../src/shopping_agent/example_checks.py` treat missing hard-constraint fields as nonmatches, require stock > 0, and rank by the task's declared rule: lowest price or highest arithmetic mean review rating (no reviews rank below reviewed items); tied winners all count. Soft preferences do not silently override hard constraints. `none` keeps every valid product. A clarification task has a question rather than a product answer.

## Trial state

Run trials sequentially. Reset before each run:

```sh
curl -X POST http://127.0.0.1:8000/internal/reset -H 'Content-Type: application/json' -d '{"task_id":"price_change"}'
```

The `price_change` task starts Ridge Rain Shell at $89. After **one successful product/search/review observation**, the next observation or cart action changes its price to $109. `GET /api/cart` does not count as an observation. The evaluator can read `GET /internal/state`; shopping agents must never receive or call this endpoint. Control routes are outside the storefront's `/api` proxy, but they are not authenticated; the later browser harness must block direct access to port 8000. Reset with `{}` for the catalog without scheduled task changes. There is one in-memory store per process, so this version does not support concurrent independent trials or persistent carts. Do not publish this server or expose the control routes to untrusted clients.

The shopper-facing endpoints are `GET /api/products?q=...&limit=...`, `GET /api/products/{product_id}`, `GET /api/products/{product_id}/reviews`, `GET /api/cart`, and `POST /api/cart` with `{"product_id":"ridge-shell","quantity":1}`. Searches are case-insensitive token matches and return sponsored listings first; no claim is made that this search behaves like a real marketplace. Cart writes reject missing products, invalid quantities, and insufficient live stock. Prices and availability may change between search and cart; no order placement exists.

To test the contracts and backend, install `requirements-dev.txt` once and run `py -m pytest` from the repository root. The agent, browser tools, and evaluator runner are later project sections and are not implemented here.
