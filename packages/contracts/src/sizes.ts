import { z } from 'zod';
import { departmentSchema, type Department } from './departments';

/**
 * Size systems + fit-slider scales (Wave S1 onboarding).
 *
 * Sourced by the onboarding "sizes" (screen 2) and "fit sliders" (screen 3)
 * screens and persisted into style_profiles.facts. Hand-written Zod, matching the
 * ./closet.ts convention. Size systems are department-scoped: dress sizes apply to
 * womens/both only (see sizeKeysForDepartment).
 */

// --- Letter sizing (tops, outerwear, and letter-system bottoms) --------------
export const LETTER_SIZES = ['XS', 'S', 'M', 'L', 'XL', 'XXL'] as const;
export const letterSizeSchema = z.enum(LETTER_SIZES);
export type LetterSize = z.infer<typeof letterSizeSchema>;

// --- Bottoms: letter OR numeric waist(×inseam), discriminated by `system` -----
export const bottomLetterSchema = z.object({
  system: z.literal('letter'),
  value: letterSizeSchema,
});
export const bottomWaistInseamSchema = z.object({
  system: z.literal('waist_inseam'),
  waist: z.number().int().min(20).max(60),
  inseam: z.number().int().min(24).max(40).optional(),
});
export const bottomSizeSchema = z.discriminatedUnion('system', [
  bottomLetterSchema,
  bottomWaistInseamSchema,
]);
export type BottomSize = z.infer<typeof bottomSizeSchema>;

// --- Shoes: system + free value (e.g. {system:'EU', value:'42'}) -------------
export const SHOE_SYSTEMS = ['US', 'EU', 'UK'] as const;
export const shoeSystemSchema = z.enum(SHOE_SYSTEMS);
export const shoeSizeSchema = z.object({
  system: shoeSystemSchema,
  value: z.string().min(1).max(8),
});
export type ShoeSize = z.infer<typeof shoeSizeSchema>;

// --- Dresses: US numeric (womens / both only) --------------------------------
export const DRESS_SIZES = ['0', '2', '4', '6', '8', '10', '12', '14', '16', '18'] as const;
export const dressSizeSchema = z.enum(DRESS_SIZES);
export type DressSize = z.infer<typeof dressSizeSchema>;

/**
 * Full per-user size profile. Every field optional — onboarding is skippable
 * screen-by-screen, and department gates which keys are shown (dress womens-only).
 */
export const sizeProfileSchema = z.object({
  top: letterSizeSchema.optional(),
  bottom: bottomSizeSchema.optional(),
  shoe: shoeSizeSchema.optional(),
  dress: dressSizeSchema.optional(),
  outerwear: letterSizeSchema.optional(),
});
export type SizeProfile = z.infer<typeof sizeProfileSchema>;

/**
 * Which size keys the sizes screen renders for a department. Dress is womens/both
 * only; every other key is universal.
 */
export function sizeKeysForDepartment(dept: Department): (keyof SizeProfile)[] {
  const base: (keyof SizeProfile)[] = ['top', 'bottom', 'shoe', 'outerwear'];
  return dept === 'womens' || dept === 'both' ? [...base, 'dress'] : base;
}

// --- Fit sliders (screen 3): integer 1..5, 3 = neutral -----------------------
export const fitSliderSchema = z.number().int().min(1).max(5);
export type FitSlider = z.infer<typeof fitSliderSchema>;

/** Slider axes + their pole labels, in render order. */
export const FIT_SLIDERS = [
  { key: 'top', label: 'Tops', min: 'Fitted', max: 'Oversized' },
  { key: 'bottom', label: 'Bottoms', min: 'Slim', max: 'Wide' },
] as const;

export const fitPreferencesSchema = z.object({
  top: fitSliderSchema.optional(),
  bottom: fitSliderSchema.optional(),
});
export type FitPreferences = z.infer<typeof fitPreferencesSchema>;

/**
 * Convenience: the shape onboarding stages client-side across screens 1-3 before
 * the single POST /onboarding/seed. Mirrors (a subset of) style_profiles.facts.
 */
export const onboardingFactsSchema = z.object({
  department: departmentSchema.optional(),
  sizes: sizeProfileSchema.optional(),
  fits: fitPreferencesSchema.optional(),
});
export type OnboardingFacts = z.infer<typeof onboardingFactsSchema>;
