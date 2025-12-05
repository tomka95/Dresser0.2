import { z } from 'zod';

/**
 * ClosetItem schema and type
 */
export const closetItemSchema = z.object({
  id: z.string().uuid(),
  userId: z.string().uuid(),
  name: z.string().min(1),
  category: z.enum(['top', 'bottom', 'dress', 'outerwear', 'shoes', 'accessories', 'other']),
  color: z.string().optional(),
  brand: z.string().optional(),
  imageUrl: z.string().url().optional(),
  createdAt: z.string().datetime(),
  updatedAt: z.string().datetime(),
});

export type ClosetItem = z.infer<typeof closetItemSchema>;



