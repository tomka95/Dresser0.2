import { z } from 'zod';

/**
 * A saved outfit as served by the real backend (GET /outfits — saved_outfits
 * rows: chat saves, worn Today's Looks, on-demand composer generates).
 *
 * `items` are the caller's OWN ClosetItem ids, validated server-side at save
 * time; `isLiked` is the server-persisted Lookbook heart (migration 0043).
 * The legacy mock-era `recommendedItems` field is gone — the backend never
 * fabricates shopping suggestions inside an outfit.
 */
export const outfitSuggestionSchema = z.object({
  id: z.string().uuid(),
  userId: z.string().uuid(),
  name: z.string().min(1).optional().nullable(),
  items: z.array(z.string().uuid()), // Array of ClosetItem IDs
  occasion: z.string().optional().nullable(),
  rationale: z.string().optional().nullable(),
  source: z.enum(['chat', 'composer']),
  status: z.enum(['active', 'worn', 'rejected', 'archived']),
  isLiked: z.boolean(),
  createdAt: z.string(),
});

export type OutfitSuggestion = z.infer<typeof outfitSuggestionSchema>;

/** POST /outfits/generate result. When the closet can't complete a look the
 * server answers honestly: saved=false, sufficient=false, the composer's own
 * gap list, and nothing is persisted. */
export interface GenerateOutfitResult {
  saved: boolean;
  sufficient: boolean;
  gaps: string[];
  note?: string | null;
  outfit?: OutfitSuggestion | null;
  idempotent?: boolean;
}
