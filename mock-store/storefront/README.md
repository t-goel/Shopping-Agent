# Goodthings storefront

A responsive React + Vite mock storefront. The UI includes product search and category filters, sponsored labels, stock/price/rating metadata, product details, and an interactive cart. It does not offer checkout or payment.

## Run locally

From this directory:

```sh
npm install
npm run dev
```

Vite proxies `/api` requests to `http://localhost:8000`. Start the backend separately on port 8000. If it is unavailable, the storefront displays an error rather than inventing product or cart state.

## API shape used

- `GET /api/products?q=` returns an array of products (or `{ "products": [...] }`).
- `GET /api/products/{id}` returns a product.
- `GET /api/cart` returns `{ "items": [], "total": 0, "currency": "USD" }`.
- `POST /api/cart` accepts `{ "product_id": "...", "quantity": 1 }` and returns the updated cart.

Product cards use `product_id`, `title`, `description`, `category`, numeric `price` in USD, integer `stock`, `seller`, `rating`, `review_count`, `attributes`, `sponsored`, and optional `image_url`. Cart line items use `product_id`, `quantity`, `unit_price`, and `line_total`.

## Build

```sh
npm run build
```
