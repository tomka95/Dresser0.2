/**
 * Shop suggestions client — MOCK / NOT BACKED.
 *
 * The unified Search screen shows shoppable "complete the look" tiles alongside
 * owned closet items. There is no backend product-search/recommendation endpoint
 * yet, so these are static suggestions. When a real endpoint exists (e.g.
 * GET /shop/suggest?q=...), swap the body of suggestShopItems() to call it.
 */

export interface ShopItem {
  id: string;
  name: string;
  brand: string;
  price: number;
  currency: string;
  imageUrl: string;
}

const MOCK_SHOP: ShopItem[] = [
  {
    id: 's1',
    name: 'Pleated Trousers',
    brand: 'Arket',
    price: 99,
    currency: 'USD',
    imageUrl:
      'https://images.unsplash.com/photo-1473966968600-fa801b869a1a?q=80&w=500&auto=format&fit=crop',
  },
  {
    id: 's2',
    name: 'Suede Loafers',
    brand: 'Mango',
    price: 129,
    currency: 'USD',
    imageUrl:
      'https://images.unsplash.com/photo-1533867617858-e7b97e060509?q=80&w=500&auto=format&fit=crop',
  },
  {
    id: 's3',
    name: 'Oversized Tee',
    brand: 'COS',
    price: 45,
    currency: 'USD',
    imageUrl:
      'https://images.unsplash.com/photo-1583743814966-8936f5b7be1a?q=80&w=500&auto=format&fit=crop',
  },
  {
    id: 's4',
    name: 'Denim Overshirt',
    brand: 'Levi’s',
    price: 118,
    currency: 'USD',
    imageUrl:
      'https://images.unsplash.com/photo-1576871337622-98d48d1cf531?q=80&w=500&auto=format&fit=crop',
  },
];

/** Returns shoppable suggestions. `query` is accepted for forward-compat but ignored (mock). */
export async function suggestShopItems(_query?: string): Promise<ShopItem[]> {
  return MOCK_SHOP;
}
