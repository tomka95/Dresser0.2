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
