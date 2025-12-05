import { z } from 'zod';

/**
 * Items that we recommend the user add to their closet
 * (e.g., "buy a denim jacket to complete this outfit").
 */
export const recommendedItemSchema = z.object({
  id: z.string().uuid(),
  name: z.string().min(1),
  reason: z.string().optional(),
});

export type RecommendedItem = z.infer<typeof recommendedItemSchema>;

/**
 * OutfitSuggestion schema and type
 * Minimal shape needed for UI display
 */
export const outfitSuggestionSchema = z.object({
  id: z.string().uuid(),
  userId: z.string().uuid(),
  name: z.string().min(1).optional(),
  items: z.array(z.string().uuid()), // Array of ClosetItem IDs
  occasion: z.string().optional(),
  recommendedItems: z.array(recommendedItemSchema).optional(),
  createdAt: z.string().datetime(),
});

export type OutfitSuggestion = z.infer<typeof outfitSuggestionSchema>;

