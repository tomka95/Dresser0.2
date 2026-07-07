/**
 * Mock shoppable-suggestion catalog — mirrors the design gallery's data set.
 * FRONTEND-ONLY: there is no shop/search backend yet; /search and /shop/[id]
 * render from this list until a real endpoint exists.
 */

export interface ShopProduct {
  id: string;
  name: string;
  brand: string;
  price: number;
  img: string;
  /** AI rationale line shown on the product detail screen. */
  reason: string;
  sizes: string[];
  recommendedSize: string;
}

export const SHOP_PRODUCTS: ShopProduct[] = [
  {
    id: 's1',
    name: 'Pleated Trousers',
    brand: 'Arket',
    price: 99,
    img: 'https://images.unsplash.com/photo-1473966968600-fa801b869a1a?q=80&w=500&auto=format&fit=crop',
    reason: 'Pairs with your linen shirt and chelsea boots — fills the smart-trouser gap in your closet.',
    sizes: ['28', '30', '32', '34', '36'],
    recommendedSize: '32',
  },
  {
    id: 's2',
    name: 'Suede Loafers',
    brand: 'Mango',
    price: 129,
    img: 'https://images.unsplash.com/photo-1533867617858-e7b97e060509?q=80&w=500&auto=format&fit=crop',
    reason: 'A smarter step for your tailored looks — works with both your jeans and trousers.',
    sizes: ['41', '42', '43', '44', '45'],
    recommendedSize: '43',
  },
  {
    id: 's3',
    name: 'Oversized Tee',
    brand: 'COS',
    price: 45,
    img: 'https://images.unsplash.com/photo-1583743814966-8936f5b7be1a?q=80&w=500&auto=format&fit=crop',
    reason: 'An easy layer under your leather jacket — you reach for white tees the most.',
    sizes: ['S', 'M', 'L', 'XL'],
    recommendedSize: 'M',
  },
  {
    id: 's4',
    name: 'Denim Overshirt',
    brand: "Levi's",
    price: 118,
    img: 'https://images.unsplash.com/photo-1576871337622-98d48d1cf531?q=80&w=500&auto=format&fit=crop',
    reason: 'Bridges your casual and smart sides — layers over most of your tops.',
    sizes: ['S', 'M', 'L', 'XL'],
    recommendedSize: 'M',
  },
];

export function getShopProduct(id: string): ShopProduct | undefined {
  return SHOP_PRODUCTS.find((p) => p.id === id);
}

/* ──────────────────────────────────────────────────────────────────────────
   ROADMAP (P2) mock shapes — these back the preview-only screens (F6 rate-a-look,
   F7 saved, F8 packing, F9 creator closet). There is NO backend for any of them;
   the screens render from these and label themselves as previews / device-only.
   ────────────────────────────────────────────────────────────────────────── */

/** F8 · Packing — a trip and the (mock) count of looks it generates. */
export interface PackingMock {
  trip: string;
  temp: string;
  /** How many looks the (roadmap) generator would build. */
  looks: number;
}

export const PACKING_MOCK: PackingMock = {
  trip: 'Lisbon · 4 days',
  temp: '19–24°',
  looks: 5,
};

/** F9 · Creator closet — a public, shoppable closet (fully mock preview). */
export interface CreatorMock {
  name: string;
  handle: string;
  followers: string;
  pieces: number;
  shoppable: number;
  /** Initials for the avatar disc. */
  initials: string;
}

export const CREATOR_MOCK: CreatorMock = {
  name: 'Lena Moreau',
  handle: '@lenamoreau',
  followers: '212k',
  pieces: 148,
  shoppable: 37,
  initials: 'LM',
};

/** A saved/wishlist entry (F7) — a mock product plus an optional price-drop. */
export interface SavedMock extends ShopProduct {
  /** Present when the (roadmap) watcher spotted a drop. Device-only, not live. */
  priceDrop?: { pct: number; was: number };
}

export const SAVED_MOCK: SavedMock[] = [
  { ...SHOP_PRODUCTS[0] },
  { ...SHOP_PRODUCTS[1], priceDrop: { pct: 20, was: 161 } },
  { ...SHOP_PRODUCTS[2] },
  { ...SHOP_PRODUCTS[3] },
];
