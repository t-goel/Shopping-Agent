import React, { useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import './styles.css';

const money = amount => new Intl.NumberFormat('en-US', {
  style: 'currency', currency: 'USD',
}).format(amount);

async function readJson(url, options) {
  const response = await fetch(url, options);
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || `Store request failed (${response.status})`);
  }
  return response.json();
}

function App() {
  const [products, setProducts] = useState([]);
  const [query, setQuery] = useState('');
  const [category, setCategory] = useState('All');
  const [selected, setSelected] = useState(null);
  const [cart, setCart] = useState({ items: [], total: 0 });
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [cartOpen, setCartOpen] = useState(false);

  // Read the authoritative catalog and cart; an offline backend is an error, not a second catalog.
  useEffect(() => {
    Promise.all([readJson('/api/products'), readJson('/api/cart')])
      .then(([items, basket]) => { setProducts(items); setCart(basket); })
      .catch(err => setError(err.message))
      .finally(() => setLoading(false));
  }, []);

  // A search is always a server observation, including an empty query that resets the results.
  async function search(event) {
    event.preventDefault();
    setLoading(true);
    setError('');
    setCategory('All');
    try {
      setProducts(await readJson(`/api/products?q=${encodeURIComponent(query.trim())}`));
    } catch (err) {
      setProducts([]);
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  async function openProduct(product) {
    setError('');
    try {
      setSelected(await readJson(`/api/products/${encodeURIComponent(product.product_id)}`));
    } catch (err) {
      setError(err.message);
    }
  }

  // Commit cart additions only after the backend verifies live stock and returns the current total.
  async function addToCart(product) {
    setError('');
    try {
      const basket = await readJson('/api/cart', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ product_id: product.product_id, quantity: 1 }),
      });
      setCart(basket);
      setSelected(null);
      setCartOpen(true);
    } catch (err) {
      setError(err.message);
      try {
        setSelected(await readJson(`/api/products/${encodeURIComponent(product.product_id)}`));
      } catch { /* Keep the visible error when a listing disappears. */ }
    }
  }

  const categories = ['All', ...new Set(products.map(p => p.category))];
  const visible = category === 'All' ? products : products.filter(p => p.category === category);
  const cartCount = cart.items.reduce((sum, item) => sum + item.quantity, 0);

  return (
    <>
      <header className="header">
        <a className="brand" href="/">Goodthings<span>.</span></a>
        <nav aria-label="Main navigation"><a href="#shop">Shop products</a></nav>
        <button type="button" onClick={() => setCartOpen(true)}>Cart ({cartCount})</button>
      </header>
      <main>
        <section className="intro">
          <p className="eyebrow">A small mock shop</p>
          <h1>Find a good thing.</h1>
          <p>Browse products, read the details, and compare what matters to you.</p>
        </section>
        <section className="shop" id="shop" aria-labelledby="shop-title">
          <div className="shop-heading">
            <h2 id="shop-title">Shop products</h2>
            <form onSubmit={search} role="search">
              <label htmlFor="product-search">Search products</label>
              <div className="search-fields">
                <input id="product-search" value={query} onChange={event => setQuery(event.target.value)} placeholder="e.g. waterproof jacket" />
                <button type="submit">Search</button>
              </div>
            </form>
          </div>
          {error && <p className="error" role="alert">{error}</p>}
          {loading ? <p role="status">Loading products…</p> : (
            <>
              <div className="categories" role="group" aria-label="Product category">
                {categories.map(name => <button type="button" key={name} aria-pressed={name === category} onClick={() => setCategory(name)}>{name}</button>)}
              </div>
              {visible.length === 0 ? <p>No products found.</p> : (
                <div className="grid">
                  {visible.map(product => <article className="card" key={product.product_id}>
                    <div className="card-art" aria-hidden="true">{product.category === 'bags' ? '◈' : '◇'}</div>
                    <div className="card-body">
                      <div className="tag-row">{product.sponsored && <span className="sponsored">Sponsored</span>}<span>{product.category}</span></div>
                      <h3>{product.title}</h3>
                      <p>{product.description}</p>
                      <p>Sold by {product.seller}</p>
                      <p>{product.rating === null ? 'No reviews yet' : `Rating ${product.rating} / 5 (${product.review_count} reviews)`}</p>
                      <div className="card-footer"><strong>{money(product.price)}</strong><span>{product.stock > 0 ? `${product.stock} in stock` : 'Out of stock'}</span></div>
                      <button type="button" onClick={() => openProduct(product)}>View details for {product.title}</button>
                    </div>
                  </article>)}
                </div>
              )}
            </>
          )}
        </section>
      </main>
      {selected && <div className="overlay" role="presentation">
        <section className="dialog" role="dialog" aria-modal="true" aria-labelledby="product-title">
          <button className="close" type="button" onClick={() => setSelected(null)} aria-label="Close product details">×</button>
          <p className="eyebrow">{selected.category}</p>
          <h2 id="product-title">{selected.title}</h2>
          {error && <p className="error" role="alert">{error}</p>}
          <p>{selected.description}</p>
          <p>Sold by {selected.seller}</p>
          <dl>{Object.entries(selected.attributes).map(([key, value]) => <div key={key}><dt>{key.replaceAll('_', ' ')}</dt><dd>{String(value)}</dd></div>)}</dl>
          <h3>Reviews</h3>
          {selected.reviews.length ? <ul>{selected.reviews.map(review => <li key={review.review_id}>{review.rating} / 5: {review.text}</li>)}</ul> : <p>No reviews yet.</p>}
          <p><strong>{money(selected.price)}</strong> · {selected.stock > 0 ? `${selected.stock} in stock` : 'Out of stock'}</p>
          <button type="button" disabled={selected.stock === 0} onClick={() => addToCart(selected)}>Add to cart</button>
        </section>
      </div>}
      {cartOpen && <div className="overlay" role="presentation">
        <section className="dialog" role="dialog" aria-modal="true" aria-labelledby="cart-title">
          <button className="close" type="button" onClick={() => setCartOpen(false)} aria-label="Close cart">×</button>
          <h2 id="cart-title">Cart</h2>
          {cart.items.length ? <ul>{cart.items.map(item => (
            <li key={item.product_id}>{item.product_id} · {item.quantity} × {money(item.unit_price)} = {money(item.line_total)}</li>
          ))}</ul> : <p>Your cart is empty.</p>}
          <p><strong>Total: {money(cart.total)}</strong></p>
          <p>Checkout and payments are not available in this mock store.</p>
        </section>
      </div>}
    </>
  );
}

createRoot(document.getElementById('root')).render(<App />);
