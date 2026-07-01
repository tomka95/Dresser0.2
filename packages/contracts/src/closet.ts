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
  size: z.string().optional(),
  quantity: z.number().int().min(1).optional(),
  unitPrice: z.number().optional(),
  currency: z.string().optional(),
  orderDate: z.string().optional(),
  isReturn: z.boolean().optional(),
  merchant: z.string().optional(),
  imageUrl: z.string().url().optional(),
  // TODO: define expected analysis_raw JSON shape (user will provide example)
  analysisRaw: z.unknown().optional(),
  createdAt: z.string().datetime(),
  updatedAt: z.string().datetime(),
});

export type ClosetItem = z.infer<typeof closetItemSchema>;

/**
 * ClosetItemUpdate schema and type
 * Partial updates for PATCH requests
 */
export const closetItemUpdateSchema = z.object({
  name: z.string().min(1).optional(),
  category: z.enum(['top', 'bottom', 'dress', 'outerwear', 'shoes', 'accessories', 'other']).optional(),
  color: z.string().optional(),
  brand: z.string().optional(),
  size: z.string().optional(),
  unitPrice: z.number().optional(),
  currency: z.string().optional(),
  imageUrl: z.string().url().optional(),
  // TODO: define expected analysis_raw JSON shape (user will provide example)
  analysisRaw: z.unknown().optional(),
});

export type ClosetItemUpdate = z.infer<typeof closetItemUpdateSchema>;






