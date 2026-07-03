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
  // --- AI Stylist universal garment schema (Wave S0) -------------------------
  // Optional passthrough; populated by Branch B. category enum intentionally
  // unchanged here (Branch B/C widen it to the 12-value set when the UI handles
  // them). All optional to match the existing nullable-field convention above.
  subCategory: z.string().optional(),
  colorPrimaryHex: z.string().optional(),
  colorSecondary: z.string().optional(),
  pattern: z.string().optional(),
  material: z.string().optional(),
  fitSilhouette: z.string().optional(),
  fitRise: z.string().optional(),
  formality: z.number().int().min(1).max(5).optional(),
  warmth: z.number().int().min(1).max(3).optional(),
  seasons: z.array(z.string()).optional(),
  occasions: z.array(z.string()).optional(),
  length: z.string().optional(),
  neckline: z.string().optional(),
  sleeveLength: z.string().optional(),
  heelHeight: z.string().optional(),
  acquiredDate: z.string().optional(),
  condition: z.string().optional(),
  isFavorite: z.boolean().optional(),
  archivedAt: z.string().optional(),
  wearCount: z.number().int().optional(),
  lastWornAt: z.string().optional(),
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






