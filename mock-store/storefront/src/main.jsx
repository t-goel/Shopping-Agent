import React, { useEffect, useMemo, useState } from 'react';
import { createRoot } from 'react-dom/client';
import './styles.css';
import {
  aboutBullets, bestSellerBadge, boughtLabel, choiceBadge, colorVariants,
  deliveryLines, discountPct, FALLBACK_PRODUCT_IMAGE, fbtIds, listPrice, productImages, resellerOffer,
  reviewHistogram, sizeVariants, PHOTO_STREAM_CAPTIONS, sentimentData,
} from './chrome.js';

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

function Stars({ rating }) {
  if (rating == null) return <span className="stars muted">No ratings</span>;
  const full = Math.round(rating);
  return (
    <span className="stars" aria-label={`${rating} out of 5`}>
      {'★★★★★'.slice(0, full)}{'☆☆☆☆☆'.slice(0, 5 - full)}
      <span className="star-num">{rating}</span>
    </span>
  );
}

function App() {
  const [products, setProducts] = useState([]);
  const [catalog, setCatalog] = useState([]);
  const [query, setQuery] = useState('');
  const [category, setCategory] = useState('All');
  const [brand, setBrand] = useState('All');
  const [minStars, setMinStars] = useState(0);
  const [selected, setSelected] = useState(null);
  const [condition, setCondition] = useState('new');
  const [qty, setQty] = useState(1);
  const [coupon, setCoupon] = useState(false);
  const [protect, setProtect] = useState(false);
  const [cart, setCart] = useState({ items: [], total: 0 });
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [loading, setLoading] = useState(true);
  const [cartOpen, setCartOpen] = useState(false);
  const [fulfillment, setFulfillment] = useState('shipping');
  const [accordion, setAccordion] = useState({ details: true });

  useEffect(() => {
    Promise.all([readJson('/api/products'), readJson('/api/cart')])
      .then(([items, basket]) => {
        setProducts(items);
        setCatalog(items);
        setCart(basket);
      })
      .catch(err => setError(err.message))
      .finally(() => setLoading(false));
  }, []);

  async function search(event) {
    event.preventDefault();
    setLoading(true);
    setError('');
    setCategory('All');
    setSelected(null);
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
    setNotice('');
    setCondition('new');
    setFulfillment('shipping');
    setQty(1);
    setCoupon(false);
    setProtect(false);
    try {
      setSelected(await readJson(`/api/products/${encodeURIComponent(product.product_id)}`));
      window.scrollTo(0, 0);
    } catch (err) {
      setError(err.message);
    }
  }

  async function addToCart(product, quantity = 1) {
    setError('');
    setNotice('');
    try {
      let basket = cart;
      for (let i = 0; i < quantity; i += 1) {
        basket = await readJson('/api/cart', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ product_id: product.product_id, quantity: 1 }),
        });
      }
      setCart(basket);
      setCartOpen(true);
    } catch (err) {
      setError(err.message);
      try {
        setSelected(await readJson(`/api/products/${encodeURIComponent(product.product_id)}`));
      } catch { /* keep error */ }
    }
  }

  async function addBundle(ids) {
    setError('');
    setNotice('');
    try {
      let basket = cart;
      for (const id of ids) {
        const item = catalog.find(p => p.product_id === id);
        if (!item || item.stock <= 0) continue;
        basket = await readJson('/api/cart', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ product_id: id, quantity: 1 }),
        });
      }
      setCart(basket);
      setCartOpen(true);
      setNotice('Complete kit items were added to your bag.');
    } catch (err) {
      setError(err.message);
    }
  }

  const sellers = useMemo(
    () => ['All', ...new Set(catalog.map(p => p.seller))],
    [catalog],
  );

  const visible = products.filter(p => {
    if (category !== 'All' && p.category !== category) return false;
    if (brand !== 'All' && p.seller !== brand) return false;
    if (minStars > 0 && (p.rating == null || p.rating < minStars)) return false;
    return true;
  });

  const cartCount = cart.items.reduce((sum, item) => sum + item.quantity, 0);
  const cartLines = cart.items.map(item => {
    const product = catalog.find(p => p.product_id === item.product_id);
    return { item, product };
  });
  const images = selected ? productImages(selected) : [];
  const hist = selected ? reviewHistogram(selected) : null;
  const sentiment = selected ? sentimentData(selected) : null;
  const siblings = selected
    ? catalog.filter(p => p.category === selected.category && p.product_id !== selected.product_id)
    : [];
  const ctaLabel = {
    shipping: 'Ship it',
    pickup: 'Pick up',
    courier: 'Dispatch today',
  }[fulfillment] || 'Add to Bag';
  const fbt = selected ? fbtIds(selected) : null;
  const fbtProducts = fbt ? fbt.map(id => catalog.find(p => p.product_id === id)).filter(Boolean) : [];
  const fbtTotal = fbtProducts.reduce((s, p) => s + p.price, 0);
  const reseller = selected ? resellerOffer(selected) : null;
  const resellerProduct = reseller ? catalog.find(p => p.product_id === reseller.product_id) : null;
  const sizes = selected ? sizeVariants(selected) : null;
  const colors = selected ? colorVariants(selected) : null;
  const delivery = selected ? deliveryLines(selected) : null;
  const activePrice = condition === 'used' && resellerProduct ? resellerProduct.price : selected?.price;

  return (
    <>
      <header className="topnav">
        <a className="brand" href="/" onClick={event => { event.preventDefault(); setSelected(null); }}>Goodthings</a>
        <form className="nav-search" onSubmit={search} role="search">
          <label className="sr-only" htmlFor="product-search">Search</label>
          <select aria-label="Department" defaultValue="All">
            <option>All</option>
            <option>jackets</option>
            <option>bags</option>
            <option>footwear</option>
          </select>
          <input id="product-search" value={query} onChange={event => setQuery(event.target.value)} placeholder="Search the trail shop" />
          <button type="submit">Search</button>
        </form>
        <button type="button" className="cart-btn" onClick={() => setCartOpen(true)}>Bag ({cartCount})</button>
      </header>
      <nav className="subnav" aria-label="Shortcuts">
        <button type="button" onClick={() => { setSelected(null); setCategory('All'); }}>All</button>
        <button type="button" onClick={() => { setSelected(null); setCategory('jackets'); }}>Jackets</button>
        <button type="button" onClick={() => { setSelected(null); setCategory('bags'); }}>Bags</button>
        <button type="button" onClick={() => { setSelected(null); setCategory('footwear'); }}>Footwear</button>
        <button type="button" className="ghost">Trail deals</button>
        <button type="button" className="ghost">Care desk</button>
      </nav>

      {error && <p className="banner error" role="alert">{error}</p>}
      {notice && <p className="banner notice" role="status">{notice}</p>}

      {selected ? (
        <main className="pdp">
          <p className="crumbs">Outdoor / {selected.category} / {selected.title}</p>
          <div className="pdp-split">
            <section className="photo-stream" aria-label="Product photos">
              {images.map((src, i) => (
                <figure key={src + i} className="photo-stream-card">
                  <img src={src} alt={`${selected.title} view ${i + 1}`} loading={i === 0 ? 'eager' : 'lazy'} />
                  <figcaption className="photo-stream-caption">
                    {PHOTO_STREAM_CAPTIONS[i] || `Field perspective ${i + 1}`}
                  </figcaption>
                </figure>
              ))}
              <div className="audio-overview-card">
                <button
                  type="button"
                  className="audio-pill-btn"
                  onClick={() => setNotice('Audio gear guide: 1:15 summary of trail fit, waterproof membrane, and field specs.')}
                >
                  <span className="audio-icon">▶</span> Hear Gear Summary · 1:15
                </button>
              </div>
            </section>

            <aside className="action-rail">
              <p className="kicker">{selected.category} · {selected.seller} · SKU #{selected.product_id.toUpperCase()}</p>
              <h1 id="product-title">{selected.title}</h1>
              <div className="rating-row">
                <Stars rating={selected.rating} />
                <button type="button" className="linkish" onClick={() => setAccordion(a => ({ ...a, reviews: true }))}>
                  {selected.review_count} ratings
                </button>
              </div>
              {choiceBadge(selected) && <p className="choice-badge">Staff pick · {choiceBadge(selected)}</p>}
              {bestSellerBadge(selected) && <p className="best-badge">{bestSellerBadge(selected)}</p>}

              <div className="price-context-block">
                <div className="price-kicker-row">
                  <span className="online-price-tag">Online store price</span>
                  {condition === 'used' && <span className="preowned-tag">Pre-owned partner tier</span>}
                </div>
                <div className="price-stack">
                  <span className="price">{money(activePrice)}</span>
                  <span className="disc">-{discountPct(selected)}%</span>
                </div>
                <p className="trail-mark">
                  Trail Mark was <s>{money(listPrice(selected))}</s> · Save {money(listPrice(selected) - activePrice)}
                </p>
                <p className="card-promo">
                  Goodthings Club: Save $15.00 with member sign-in or 4 payments of {money(activePrice / 4)}
                </p>
                <p className="ship-perk">{boughtLabel(selected)}</p>
              </div>

              {colors && (
                <div className="variants">
                  <p className="variant-label">Color · {selected.attributes?.color ?? '—'}</p>
                  <div className="swatches">
                    {colors.map(v => (
                      <button
                        key={v.label}
                        type="button"
                        title={v.label}
                        className={v.product_id === selected.product_id ? 'active' : ''}
                        style={{ background: v.swatch }}
                        onClick={() => openProduct({ product_id: v.product_id })}
                      />
                    ))}
                  </div>
                </div>
              )}

              {sizes && (
                <div className="variants">
                  <div className="variant-head">
                    <p className="variant-label">Select size</p>
                    <button type="button" className="linkish">Size guide</button>
                  </div>
                  <div className="size-tiles">
                    {sizes.map(v => (
                      <button
                        key={v.label}
                        type="button"
                        aria-disabled={!v.product_id}
                        disabled={!v.product_id}
                        className={[
                          v.product_id === selected.product_id ? 'active' : '',
                          !v.product_id ? 'oos-slash' : '',
                        ].join(' ')}
                        onClick={() => v.product_id && openProduct({ product_id: v.product_id })}
                      >
                        {v.label}
                      </button>
                    ))}
                  </div>
                </div>
              )}

              <div className="segmented" role="group" aria-label="Condition">
                <button type="button" className={condition === 'new' ? 'on' : ''} onClick={() => setCondition('new')}>
                  New · {money(selected.price)}
                </button>
                {resellerProduct && (
                  <button type="button" className={condition === 'used' ? 'on' : ''} onClick={() => setCondition('used')}>
                    Pre-owned · {money(resellerProduct.price)}
                  </button>
                )}
              </div>

              <div className="fulfillment-group" role="radiogroup" aria-label="Fulfillment method">
                <button
                  type="button"
                  role="radio"
                  aria-checked={fulfillment === 'shipping'}
                  className={`fulfillment-card ${fulfillment === 'shipping' ? 'active' : ''}`}
                  onClick={() => setFulfillment('shipping')}
                >
                  <div className="ful-header">
                    <span className="ful-radio-circle" />
                    <span className="ful-method">Trail Pass Shipping</span>
                  </div>
                  <span className="ful-desc">Arrives in 2–3 business days · Free over $49</span>
                </button>
                <button
                  type="button"
                  role="radio"
                  aria-checked={fulfillment === 'pickup'}
                  className={`fulfillment-card ${fulfillment === 'pickup' ? 'active' : ''}`}
                  onClick={() => setFulfillment('pickup')}
                >
                  <div className="ful-header">
                    <span className="ful-radio-circle" />
                    <span className="ful-method">Outpost Pickup</span>
                  </div>
                  <span className="ful-desc">Ready in 2 hours at Downtown Outpost · Free</span>
                </button>
                <button
                  type="button"
                  role="radio"
                  aria-checked={fulfillment === 'courier'}
                  className={`fulfillment-card ${fulfillment === 'courier' ? 'active' : ''}`}
                  onClick={() => setFulfillment('courier')}
                >
                  <div className="ful-header">
                    <span className="ful-radio-circle" />
                    <span className="ful-method">Same-Day Courier</span>
                  </div>
                  <span className="ful-desc">Delivered today by 7pm · Trailhead dispatch ($9.99)</span>
                </button>
              </div>

              <label className="toggle-row">
                <input type="checkbox" checked={coupon} onChange={e => setCoupon(e.target.checked)} />
                <span>Apply $5 trail credit (decorative)</span>
              </label>
              <label className="toggle-row">
                <input type="checkbox" checked={protect} onChange={e => setProtect(e.target.checked)} />
                <span>Add TrailShield protection · $12.99</span>
              </label>

              <label className="qty-inline">Qty
                <select value={qty} onChange={e => setQty(Number(e.target.value))}>
                  {[1, 2, 3, 4, 5].map(n => <option key={n} value={n}>{n}</option>)}
                </select>
              </label>

              <p className={selected.stock > 0 ? 'in-stock' : 'oos'}>
                {selected.stock > 0
                  ? (selected.stock <= 2 ? `Only ${selected.stock} left` : 'In stock')
                  : 'Currently unavailable'}
              </p>
              <p className="ships">Ships from Goodthings · Sold by {condition === 'used' && reseller ? reseller.label : selected.seller}</p>
              <p className="ships">{delivery.standard}</p>
              <p className="fast">{delivery.fastest}</p>

              <button
                type="button"
                className="cta-primary"
                disabled={selected.stock === 0 && condition === 'new'}
                onClick={() => {
                  const target = condition === 'used' && resellerProduct ? resellerProduct : selected;
                  addToCart(target, qty);
                }}
              >
                {selected.stock === 0 && condition === 'new' ? 'Unavailable' : ctaLabel}
              </button>
              <button type="button" className="cta-ghost" onClick={() => setNotice('Wishlist is decorative chrome.')}>
                Save to Trail Wishlist
              </button>
              <button
                type="button"
                className="cta-link"
                onClick={() => setNotice('Express checkout is unavailable. Use Add to Bag.')}
              >
                Express checkout
              </button>

              {resellerProduct && condition === 'new' && (
                <div className="partner-offer">
                  <p>Also from {reseller.label}</p>
                  <p>{money(resellerProduct.price)} · partner fulfillment</p>
                  <button type="button" className="linkish" onClick={() => openProduct(resellerProduct)}>View partner listing</button>
                </div>
              )}

              <div className="acc">
                <button type="button" onClick={() => setAccordion(a => ({ ...a, details: !a.details }))}>
                  {accordion.details ? '−' : '+'} Product details & field specs
                </button>
                {accordion.details && (
                  <>
                    <ul className="about">{aboutBullets(selected).map(line => <li key={line}>{line}</li>)}</ul>
                    <table className="specs">
                      <tbody>
                        <tr><th>Brand</th><td>{selected.seller}</td></tr>
                        {Object.entries(selected.attributes).map(([k, v]) => (
                          <tr key={k}><th>{k.replaceAll('_', ' ')}</th><td>{String(v)}</td></tr>
                        ))}
                        <tr><th>Lab note</th><td>Trust attribute rows over marketing bullets.</td></tr>
                      </tbody>
                    </table>
                  </>
                )}
              </div>
              <div className="acc">
                <button type="button" onClick={() => setAccordion(a => ({ ...a, ship: !a.ship }))}>
                  {accordion.ship ? '−' : '+'} Shipping & partner policies
                </button>
                {accordion.ship && (
                  <p>Synthetic shipping drawer. Partner/pre-owned SKUs may ship slower than Trail Pass items.</p>
                )}
              </div>
              <div className="acc">
                <button type="button" onClick={() => setAccordion(a => ({ ...a, reviews: !a.reviews }))}>
                  {accordion.reviews ? '−' : '+'} Reviews ({hist.total})
                </button>
                {accordion.reviews && (
                  <div className="rail-reviews">
                    <Stars rating={selected.rating} />
                    {[5, 4, 3, 2, 1].map(star => {
                      const pct = hist.total ? Math.round((hist.counts[star] / hist.total) * 100) : 0;
                      return (
                        <div className="hist-row" key={star}>
                          <span>{star}★</span>
                          <div className="bar"><i style={{ width: `${pct}%` }} /></div>
                          <span>{pct}%</span>
                        </div>
                      );
                    })}
                    {selected.reviews.length ? selected.reviews.map(review => (
                      <blockquote key={review.review_id}>
                        <Stars rating={review.rating} />
                        <p>{review.text}</p>
                      </blockquote>
                    )) : <p>No reviews yet.</p>}
                  </div>
                )}
              </div>
            </aside>
          </div>

          <section className="full-specs-section">
            <h2>Specifications & trail fit</h2>
            <div className="specs-table-wrapper">
              <table className="specs-2col">
                <tbody>
                  <tr>
                    <th>Brand / Outfitter</th>
                    <td>{selected.seller}</td>
                    <th>Category</th>
                    <td>{selected.category}</td>
                  </tr>
                  <tr>
                    <th>Catalog Item ID</th>
                    <td>{selected.product_id}</td>
                    <th>Field Inventory</th>
                    <td>{selected.stock > 0 ? `${selected.stock} units in stock` : 'Out of stock'}</td>
                  </tr>
                  {(() => {
                    const entries = Object.entries(selected.attributes);
                    const rows = [];
                    for (let i = 0; i < entries.length; i += 2) {
                      const [k1, v1] = entries[i];
                      const pair = entries[i + 1];
                      rows.push(
                        <tr key={k1}>
                          <th>{k1.replaceAll('_', ' ')}</th>
                          <td>{String(v1)}</td>
                          {pair ? (
                            <>
                              <th>{pair[0].replaceAll('_', ' ')}</th>
                              <td>{String(pair[1])}</td>
                            </>
                          ) : (
                            <>
                              <th>Field Verification</th>
                              <td>Standard trail spec</td>
                            </>
                          )}
                        </tr>
                      );
                    }
                    return rows;
                  })()}
                  <tr>
                    <th>Trail Guarantee</th>
                    <td>Goodthings 100% Trail Satisfaction Guarantee</td>
                    <th>Field Lab Note</th>
                    <td>Trust attribute rows over marketing bullets. Verified by Goodthings Field Lab.</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </section>

          <section className="reviews-section">
            <h2>Field ratings & trail sentiment</h2>
            <div className="sentiment-card">
              <div className="sentiment-summary-row">
                <div className="sentiment-score">
                  <Stars rating={selected.rating} />
                  <span className="sentiment-average">{selected.rating ?? '—'} / 5</span>
                  <span className="sentiment-count">({selected.review_count} verified field reports)</span>
                </div>
                <div className="sentiment-recommend-badge">
                  <span>✓ 94% of field testers recommend this gear</span>
                </div>
              </div>

              {sentiment && (
                <div className="sentiment-grid">
                  <div className="sentiment-box pros">
                    <span className="sentiment-title">Trail Pros</span>
                    <ul>
                      {sentiment.pros.map(item => (
                        <li key={item.label}>
                          <span className="bullet">✓</span> {item.label} <span className="sent-cnt">({item.count})</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                  <div className="sentiment-box neutral">
                    <span className="sentiment-title">Field Notes</span>
                    <ul>
                      {sentiment.neutral.map(item => (
                        <li key={item.label}>
                          <span className="bullet">•</span> {item.label} <span className="sent-cnt">({item.count})</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                  <div className="sentiment-box cons">
                    <span className="sentiment-title">Trail Watchouts</span>
                    <ul>
                      {sentiment.cons.map(item => (
                        <li key={item.label}>
                          <span className="bullet">!</span> {item.label} <span className="sent-cnt">({item.count})</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                </div>
              )}

              {sentiment && sentiment.pills.length > 0 && (
                <div className="attribute-chips-block">
                  <span className="chips-heading">Frequent customer mentions:</span>
                  <div className="chips-flex">
                    {sentiment.pills.map(p => (
                      <span key={p.name} className="attribute-pill">
                        {p.name} <span className="pill-count">({p.count})</span>
                      </span>
                    ))}
                  </div>
                </div>
              )}

              <div className="reviews-breakdown-row">
                <div className="review-histogram-col">
                  {[5, 4, 3, 2, 1].map(star => {
                    const pct = hist.total ? Math.round((hist.counts[star] / hist.total) * 100) : 0;
                    return (
                      <div className="hist-row" key={star}>
                        <span>{star}★</span>
                        <div className="bar"><i style={{ width: `${pct}%` }} /></div>
                        <span>{pct}%</span>
                      </div>
                    );
                  })}
                </div>
                <div className="reviews-quotes-col">
                  {selected.reviews.length ? selected.reviews.map(review => (
                    <blockquote key={review.review_id} className="field-review-quote">
                      <div className="quote-header">
                        <Stars rating={review.rating} />
                        <span className="verified-tag">Verified Trail Tester</span>
                      </div>
                      <p>{review.text}</p>
                    </blockquote>
                  )) : <p className="no-reviews">No written reviews yet. Be the first to test this gear on trail.</p>}
                </div>
              </div>
            </div>
          </section>

          {fbtProducts.length >= 2 && (
            <section className="kit">
              <h2>Pack the trail · complete the kit</h2>
              <div className="kit-grid">
                {fbtProducts.map(p => (
                  <button type="button" className="kit-card" key={p.product_id} onClick={() => openProduct(p)}>
                    <div className="kit-card-img-wrap">
                      <img src={productImages(p)[0]} alt="" />
                      <span className="kit-badge">{p.category}</span>
                    </div>
                    <span className="kit-title">{p.title}</span>
                    <strong className="kit-price">{money(p.price)}</strong>
                  </button>
                ))}
              </div>
              <div className="kit-footer">
                <div className="kit-summary-info">
                  <span className="kit-summary-label">Complete {fbtProducts.length}-piece kit</span>
                  <p className="kit-total">Kit total <strong>{money(fbtTotal)}</strong></p>
                </div>
                <button type="button" className="cta-primary kit-cta" onClick={() => addBundle(fbtProducts.map(p => p.product_id))}>
                  Add complete kit to Bag
                </button>
              </div>
            </section>
          )}

          {siblings.length > 0 && (
            <section className="recommendations-shelf">
              <h2>You might also like</h2>
              <div className="shelf-track">
                {siblings.map(p => (
                  <article key={p.product_id} className="shelf-card">
                    <button type="button" className="shelf-img-btn" onClick={() => openProduct(p)}>
                      <img src={productImages(p)[0]} alt="" />
                    </button>
                    <div className="shelf-meta">
                      <span className="shelf-kicker">{p.seller} · {p.category}</span>
                      <h3>
                        <button type="button" className="title-link" onClick={() => openProduct(p)}>
                          {p.title}
                        </button>
                      </h3>
                      <div className="shelf-rating">
                        <Stars rating={p.rating} />
                        <span className="rev-count">({p.review_count})</span>
                      </div>
                      <p className="shelf-price">{money(p.price)}</p>
                      <button
                        type="button"
                        className="shelf-atc"
                        disabled={p.stock === 0}
                        onClick={() => addToCart(p)}
                      >
                        {p.stock > 0 ? 'Add to Bag' : 'Unavailable'}
                      </button>
                    </div>
                  </article>
                ))}
              </div>
            </section>
          )}

          <button type="button" className="back" onClick={() => setSelected(null)}>← Back to results</button>
        </main>
      ) : (
        <main className="results-layout">
          <aside className="facets">
            <h2>Filters</h2>
            <p className="facet-label">Category</p>
            {['All', ...new Set(catalog.map(p => p.category))].map(name => (
              <label key={name}>
                <input type="radio" name="cat" checked={category === name} onChange={() => setCategory(name)} />
                {name}
              </label>
            ))}
            <p className="facet-label">Brand</p>
            {sellers.map(name => (
              <label key={name}>
                <input type="radio" name="brand" checked={brand === name} onChange={() => setBrand(name)} />
                {name}
              </label>
            ))}
            <p className="facet-label">Customer reviews</p>
            {[4, 3, 2, 1].map(n => (
              <label key={n}>
                <input type="radio" name="stars" checked={minStars === n} onChange={() => setMinStars(n)} />
                {n}+ stars
              </label>
            ))}
            <button type="button" className="linkish" onClick={() => { setBrand('All'); setMinStars(0); setCategory('All'); }}>Clear filters</button>
          </aside>
          <section className="results" id="shop">
            <h1>Results{query ? ` for “${query}”` : ''}</h1>
            {loading ? <p role="status">Loading products…</p> : visible.length === 0 ? <p>No products found.</p> : (
              <div className="result-list">
                {visible.map(product => (
                  <article className="result-card" key={product.product_id}>
                    <button type="button" className="thumb-wrap" onClick={() => openProduct(product)}>
                      <img src={productImages(product)[0]} alt="" />
                    </button>
                    <div className="result-body">
                      {product.sponsored && <p className="sponsored-muted">Promoted listing</p>}
                      <h2><button type="button" className="title-link" onClick={() => openProduct(product)}>{product.title}</button></h2>
                      <Stars rating={product.rating} />
                      <span className="rev-count">{product.review_count} ratings</span>
                      {choiceBadge(product) && <p className="choice-badge">Staff pick</p>}
                      {bestSellerBadge(product) && <p className="best-badge">{bestSellerBadge(product)}</p>}
                      <p className="price">{money(product.price)}</p>
                      <p className="list-sm">Was <s>{money(listPrice(product))}</s> · -{discountPct(product)}%</p>
                      <p>{boughtLabel(product)}</p>
                      <p className="seller">Sold by {product.seller}</p>
                      <p className="blurb">{product.description}</p>
                      <button type="button" className="atc-sm" disabled={product.stock === 0} onClick={() => addToCart(product)}>
                        {product.stock > 0 ? 'Add to Bag' : 'Unavailable'}
                      </button>
                    </div>
                  </article>
                ))}
              </div>
            )}
          </section>
        </main>
      )}

      {cartOpen && (
        <div className="cart-scrim" role="presentation" onClick={() => setCartOpen(false)}>
          <aside
            className="cart-drawer"
            role="dialog"
            aria-modal="true"
            aria-labelledby="cart-title"
            onClick={event => event.stopPropagation()}
          >
            <header className="cart-head">
              <h2 id="cart-title">Bag <span>({cartCount})</span></h2>
              <button type="button" className="cart-close" onClick={() => setCartOpen(false)} aria-label="Close bag">Close</button>
            </header>

            <div className="cart-body">
              {cartLines.length === 0 ? (
                <div className="cart-empty">
                  <p>Your bag is empty.</p>
                  <button type="button" className="cta-ghost" onClick={() => setCartOpen(false)}>Keep browsing</button>
                </div>
              ) : (
                <ul className="cart-lines">
                  {cartLines.map(({ item, product }) => (
                    <li key={item.product_id}>
                      <div className="cart-thumb">
                        <img
                          src={product ? productImages(product)[0] : FALLBACK_PRODUCT_IMAGE}
                          alt=""
                        />
                      </div>
                      <div className="cart-meta">
                        <p className="cart-title">{product?.title || item.product_id}</p>
                        <p className="cart-sub">{product?.seller || 'Goodthings'} · {product?.category || 'gear'}</p>
                        <p className="cart-sub">Qty {item.quantity}</p>
                        <p className="cart-price">{money(item.unit_price)} each</p>
                      </div>
                      <p className="cart-line-total">{money(item.line_total)}</p>
                    </li>
                  ))}
                </ul>
              )}
            </div>

            <footer className="cart-foot">
              <div className="cart-summary">
                <span>Subtotal</span>
                <strong>{money(cart.total)}</strong>
              </div>
              <p className="cart-note">Shipping & taxes calculated later · checkout is mocked</p>
              <button
                type="button"
                className="cta-primary"
                disabled={cartLines.length === 0}
                onClick={() => setNotice('Checkout is unavailable in this mock store.')}
              >
                Checkout
              </button>
              <button type="button" className="cta-ghost" onClick={() => setCartOpen(false)}>
                Continue shopping
              </button>
            </footer>
          </aside>
        </div>
      )}
    </>
  );
}

createRoot(document.getElementById('root')).render(<App />);
