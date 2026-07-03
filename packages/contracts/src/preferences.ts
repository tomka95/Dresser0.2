import { z } from 'zod';

/**
 * Preference dimensions (Wave S1).
 *
 * The FIXED vocabulary shared by onboarding and the outfit composer. Onboarding
 * screens MUST send these exact strings as `dimension` to POST /onboarding/seed —
 * free-text dimensions fragment the composer's reads (a preference is UNIQUE per
 * (user_id, dimension), so 'colour' vs 'color' would silently split a user's data).
 *
 * ADDITIVE-ONLY: style_preferences.dimension persists these exact strings; never
 * rename/remove a value. Hand-written Zod, matching the ./closet.ts convention.
 */
export const PREFERENCE_DIMENSIONS = [
  'archetype', // overall taste archetype (taste deck) — value: {liked: string[]}
  'occasion', // life occasions to dress for — value: {tags: string[]}
  'color', // color affinities/aversions
  'silhouette_top', // preferred top silhouette (fitted..oversized)
  'silhouette_bottom', // preferred bottom silhouette (slim..wide)
  'formality', // dress-up vs dress-down lean
  'brand', // brand affinities
  'material', // fabric/material preferences
] as const;

export const preferenceDimensionSchema = z.enum(PREFERENCE_DIMENSIONS);
export type PreferenceDimension = z.infer<typeof preferenceDimensionSchema>;

/** Shared like/dislike/neutral polarity (matches the DB CHECK on both tables). */
export const POLARITIES = ['like', 'dislike', 'neutral'] as const;
export const polaritySchema = z.enum(POLARITIES);
export type Polarity = z.infer<typeof polaritySchema>;
