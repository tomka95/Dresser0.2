import { z } from 'zod';

/**
 * Shopping feed (Wave F2) — GET /shop.
 *
 * A page of ranked, mixed cards. Every card carries the fields the client needs for event
 * capture: `feedPosition`, `cardType`, and the `exploration` flag (echoed into the
 * impression event so exploration engagement is measurable apart from exploited positions).
 *
 * MONETIZATION BOUNDARY: cards expose a `productId`, NEVER an outbound/affiliate URL. To
 * open a product the client mints a click via POST /clicks and follows GET /out/{clickId}.
 */

/** Wire-safe product fields (no outbound URL — click via productId). */
export const feedProductSchema = z.object({
  productId: z.string().uuid(),
  name: z.string(),
  brand: z.string().nullable().optional(),
  merchant: z.string().nullable().optional(),
  imageUrl: z.string().nullable().optional(),
  price: z.number().nullable().optional(),
  currency: z.string().nullable().optional(),
  category: z.string().nullable().optional(),
});
export type FeedProduct = z.infer<typeof feedProductSchema>;

/** Fields shared by every card, consumed by the client's event emitter. */
const cardCommon = {
  feedPosition: z.number().int(),
  cardType: z.enum(['product', 'outfit']),
  exploration: z.boolean(),
  score: z.number().optional(),
};

/** ~70% of the feed: a buyable product + how many outfits it unlocks. */
export const productCardSchema = z.object({
  type: z.literal('product'),
  product: feedProductSchema,
  unlockCount: z.number().int(),
  headline: z.string(),
  gapContext: z
    .object({
      fillsEmptyOccasion: z.boolean().optional(),
      category: z.string().nullable().optional(),
    })
    .partial()
    .optional(),
  ...cardCommon,
});
export type ProductCard = z.infer<typeof productCardSchema>;

/** ~30% of the feed: owned items + 1 buyable that completes the look. */
export const outfitCardSchema = z.object({
  type: z.literal('outfit'),
  occasion: z.string().nullable().optional(),
  ownedItemIds: z.array(z.string().uuid()),
  buyable: feedProductSchema,
  buyableProductId: z.string().uuid(),
  unlockCount: z.number().int(),
  collageUrl: z.string().nullable().optional(),
  rationale: z.string(),
  ...cardCommon,
});
export type OutfitCard = z.infer<typeof outfitCardSchema>;

export const shopCardSchema = z.discriminatedUnion('type', [
  productCardSchema,
  outfitCardSchema,
]);
export type ShopCard = z.infer<typeof shopCardSchema>;

export const shopFeedResponseSchema = z.object({
  cards: z.array(shopCardSchema),
  cursor: z.number().int(),
  sessionId: z.string(),
  hasMore: z.boolean(),
  framing: z.enum(['personalized', 'starter_looks']),
  diagnostics: z.record(z.string(), z.unknown()).optional(),
});
export type ShopFeedResponse = z.infer<typeof shopFeedResponseSchema>;
