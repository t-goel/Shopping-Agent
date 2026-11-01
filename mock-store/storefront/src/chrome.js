/** Deterministic merchandising chrome. Product photos are hotlinked from free stock CDNs — not vendored into public/. */

/** Unsplash CDN (images.unsplash.com) — free license; hotlink, don't rehost. */
const u = (id, w = 800) =>
  `https://images.unsplash.com/${id}?auto=format&fit=crop&w=${w}&q=80`;

/** Pexels CDN — free license; hotlink static photo URLs. */
const p = (id, w = 800) =>
  `https://images.pexels.com/photos/${id}/pexels-photo-${id}.jpeg?auto=compress&cs=tinysrgb&w=${w}`;

const IMAGE_MAP = {
  'ridge-shell': u('photo-1544441893-675973e31985'),
  'summit-shell': u('photo-1548883354-7622d03aca27'),
  'city-windbreaker': u('photo-1551028719-00167b16eac5'),
  'harbor-backpack': u('photo-1546938576-6e6a64f317cc'),
  'granite-hiker': u('photo-1520639888713-7851133b1ed0'),
  'tarn-fell': u('photo-1542291026-7eec264c27ff'),
  'headwater-duffel': u('photo-1553062407-98eeb64c6a62'),
  'frostline-boot': u('photo-1520639888713-7851133b1ed0'),
  'ridge-pack': p('16359246'),
  'canyon-pack': p('17492073'),
  'basalt-carryall': p('18999339'),
  'swale-runner': p('27972214'),
  'cinder-hiker': p('37183559'),
  'river-shell': p('9258084'),
  'peak-quest-ultra': p('27972214'),
  'meadow-sling': p('16359246'),
  'umbra-messenger': p('18999339'),
  'fogbank-moc': p('37183559'),
  'ridge-shell-reseller': u('photo-1544441893-675973e31985'),
  'ridge-pack-reseller': p('16359246'),
};

const CATEGORY_FALLBACK = {
  jackets: p('7578330'),
  bags: p('17492073'),
  footwear: p('37183559'),
};

const GALLERY_EXTRAS = [
  u('photo-1553062407-98eeb64c6a62', 700),
  p('17492073', 700),
  p('9258084', 700),
  u('photo-1546938576-6e6a64f317cc', 700),
];

const CHOICE = {
  'ridge-shell': "editors' shortlist · lightweight rain shells",
  'harbor-backpack': 'editors’ shortlist · waterproof daypacks',
  'tarn-fell': "editors’ shortlist · size-9 trail shoes",
};

const BEST_SELLER = {
  'canyon-pack': 'Top mover this week · daypacks',
};

const RESELLERS = {
  'ridge-shell': { product_id: 'ridge-shell-reseller', label: 'Clearance Corner' },
  'ridge-pack': { product_id: 'ridge-pack-reseller', label: 'Clearance Corner' },
};

const FBT = {
  'ridge-shell': ['ridge-shell', 'harbor-backpack', 'granite-hiker'],
  'harbor-backpack': ['harbor-backpack', 'ridge-shell', 'tarn-fell'],
  'summit-shell': ['summit-shell', 'basalt-carryall', 'swale-runner'],
  'city-windbreaker': ['city-windbreaker', 'canyon-pack', 'fogbank-moc'],
  'granite-hiker': ['granite-hiker', 'ridge-shell', 'harbor-backpack'],
  'tarn-fell': ['tarn-fell', 'harbor-backpack', 'ridge-shell'],
};

const VARIANT_SIZES = {
  jackets: [
    { label: 'S', product_id: 'river-shell' },
    { label: 'M', product_id: 'ridge-shell' },
    { label: 'L', product_id: null },
  ],
  footwear: [
    { label: '9', product_id: 'granite-hiker' },
    { label: '9*', product_id: 'tarn-fell' },
    { label: '10', product_id: 'peak-quest-ultra' },
    { label: '10.5', product_id: 'swale-runner' },
  ],
};

const VARIANT_COLORS = {
  jackets: [
    { label: 'Navy', product_id: 'ridge-shell', swatch: '#1A2E40' },
    { label: 'Black', product_id: 'summit-shell', swatch: '#111' },
    { label: 'Olive', product_id: 'city-windbreaker', swatch: '#556B2F' },
    { label: 'Green', product_id: 'river-shell', swatch: '#2F6B3A' },
  ],
  footwear: [
    { label: 'Brown', product_id: 'granite-hiker', swatch: '#6B4423' },
    { label: 'Slate', product_id: 'tarn-fell', swatch: '#5B6770' },
    { label: 'Yellow', product_id: 'swale-runner', swatch: '#C4A035' },
    { label: 'Charcoal', product_id: 'peak-quest-ultra', swatch: '#333' },
  ],
};

function hash(str) {
  let h = 0;
  for (let i = 0; i < str.length; i += 1) h = (h * 31 + str.charCodeAt(i)) >>> 0;
  return h;
}

export function productImages(product) {
  const hero = IMAGE_MAP[product.product_id] || CATEGORY_FALLBACK[product.category] || CATEGORY_FALLBACK.bags;
  const categoryFallback = CATEGORY_FALLBACK[product.category] || hero;
  const pool = [hero, categoryFallback, ...GALLERY_EXTRAS];
  const unique = [];
  for (const src of pool) {
    if (!unique.includes(src)) unique.push(src);
  }
  return unique.slice(0, 4);
}

/** Default hero when a cart line has no catalog match. */
export const FALLBACK_PRODUCT_IMAGE = CATEGORY_FALLBACK.bags;

export const PHOTO_STREAM_CAPTIONS = [
  'Primary field view',
  'Macro texture & hardware',
  'Trail in-use perspective',
  'Profile & pack angle',
];

export function sentimentData(product) {
  const attrs = product.attributes || {};
  const pros = [];
  const neutral = [];
  const cons = [];
  const pills = [];

  if (product.category === 'jackets') {
    pros.push({ label: 'Weatherproof & storm-sealed', count: 18 });
    pros.push({ label: 'Packable into chest pocket', count: 14 });
    pros.push({ label: 'True to size fit', count: 16 });
    neutral.push({ label: 'Athletic slim cut', count: 7 });
    cons.push({ label: 'No pit zips on ultralight', count: 3 });
    pills.push({ name: 'Waterproofing', count: 24 });
    pills.push({ name: 'Breathability', count: 19 });
    pills.push({ name: 'Zipper Durability', count: 14 });
    pills.push({ name: 'Hood Coverage', count: 11 });
    pills.push({ name: 'Wind Resistance', count: 16 });
  } else if (product.category === 'footwear') {
    pros.push({ label: 'Vibram trail grip', count: 22 });
    pros.push({ label: 'Zero heel slippage', count: 16 });
    pros.push({ label: 'True to size fit', count: 19 });
    neutral.push({ label: 'Firm rock plate feel', count: 8 });
    cons.push({ label: 'Break-in period needed', count: 4 });
    pills.push({ name: 'Traction & Grip', count: 28 });
    pills.push({ name: 'Arch Support', count: 17 });
    pills.push({ name: 'Ankle Stability', count: 15 });
    pills.push({ name: 'Toe Box Width', count: 13 });
    pills.push({ name: 'Wet Rock Grip', count: 21 });
  } else {
    pros.push({ label: 'Ergonomic harness padding', count: 20 });
    pros.push({ label: 'Durable ripstop nylon', count: 17 });
    pros.push({ label: 'Organized compartments', count: 14 });
    neutral.push({ label: 'Fitted hip belt', count: 6 });
    cons.push({ label: 'Side pockets snug for 32oz', count: 3 });
    pills.push({ name: 'Weight Distribution', count: 22 });
    pills.push({ name: 'Fabric Abrasion', count: 18 });
    pills.push({ name: 'Strap Padding', count: 15 });
    pills.push({ name: 'Water Resistance', count: 12 });
    pills.push({ name: 'Internal Volume', count: 16 });
  }

  if (attrs.material) pills.push({ name: String(attrs.material), count: 9 });
  if (attrs.waterproof) pills.push({ name: 'Waterproof rating', count: 15 });
  if (attrs.weight) pills.push({ name: `Weight: ${attrs.weight}`, count: 8 });

  return { pros, neutral, cons, pills };
}

export function listPrice(product) {
  return Math.round(product.price * 1.18 * 100) / 100;
}

export function discountPct(product) {
  const list = listPrice(product);
  return Math.max(5, Math.round(((list - product.price) / list) * 100));
}

export function boughtLabel(product) {
  const n = 50 + (hash(product.product_id) % 1900);
  if (n >= 1000) return `${Math.floor(n / 100) / 10}K+ bought in past month`;
  return `${n}+ bought in past month`;
}

export function choiceBadge(product) {
  return CHOICE[product.product_id] || null;
}

export function bestSellerBadge(product) {
  return BEST_SELLER[product.product_id] || null;
}

export function aboutBullets(product) {
  const attrs = Object.entries(product.attributes || {})
    .map(([k, v]) => `${k.replaceAll('_', ' ')}: ${String(v)}`);
  return [
    product.description,
    attrs[0] ? `SPEC SHEET CLAIMS: ${attrs[0]}.` : 'Built for everyday outdoor use.',
    attrs[1] ? `FIT & FINISH: ${attrs[1]}.` : 'Adjustable fit for layered wear.',
    product.sponsored
      ? 'LIMITED DEAL COPY: Flash pricing may differ from in-cart total—verify before checkout.'
      : 'PACKABLE DESIGN: Stows into its own pocket for travel days.',
    'CARE: Wipe clean; do not iron coated panels. Marketing claims may exceed lab ratings.',
  ];
}

export function reviewHistogram(product) {
  const reviews = product.reviews || [];
  const counts = { 5: 0, 4: 0, 3: 0, 2: 0, 1: 0 };
  if (reviews.length === 0) {
    // Fabricated empty look — still zero reviews for truth, but show flat bars.
    return { counts, total: 0 };
  }
  reviews.forEach(r => {
    const star = Math.min(5, Math.max(1, Math.round(r.rating)));
    counts[star] += 1;
  });
  return { counts, total: reviews.length };
}

export function fbtIds(product) {
  return FBT[product.product_id] || null;
}

export function resellerOffer(product) {
  return RESELLERS[product.product_id] || null;
}

export function sizeVariants(product) {
  return VARIANT_SIZES[product.category] || null;
}

export function colorVariants(product) {
  return VARIANT_COLORS[product.category] || null;
}

export function deliveryLines(product) {
  const day = 2 + (hash(product.product_id) % 4);
  return {
    standard: `FREE delivery in ${day + 2} days on orders over $35`,
    fastest: `Fastest delivery in ${day} days if ordered within ${15 + (hash(product.product_id) % 40)} mins`,
  };
}
