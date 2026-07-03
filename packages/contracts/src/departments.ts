import { z } from 'zod';

/**
 * Department + style-archetype taxonomy (Wave S1 onboarding).
 *
 * Single source of truth for the onboarding "departments" screen and the taste
 * deck. Department scopes which size systems apply (see ./sizes) and which
 * archetype image set the taste deck pulls from
 * (apps/web/public/images/archetypes/{mens,womens}/...). Hand-written Zod,
 * matching the ./closet.ts convention (exported const tuple + z.enum + type).
 */

// ADDITIVE-ONLY: the S0 substrate persists these exact strings in
// style_profiles.facts; never rename/remove a value.
export const DEPARTMENTS = ['womens', 'mens', 'both', 'gender_neutral'] as const;
export const departmentSchema = z.enum(DEPARTMENTS);
export type Department = z.infer<typeof departmentSchema>;

export const DEPARTMENT_LABELS: Record<Department, string> = {
  womens: "Women's",
  mens: "Men's",
  both: 'Both',
  gender_neutral: 'Gender neutral',
};

// The six taste archetypes. Folder names under public/images/archetypes/{dept}/
// use these exact keys (e.g. romantic_boho-1.jpg).
export const ARCHETYPES = [
  'minimal',
  'classic',
  'street',
  'romantic_boho',
  'sporty',
  'edgy',
] as const;
export const archetypeSchema = z.enum(ARCHETYPES);
export type Archetype = z.infer<typeof archetypeSchema>;

export const ARCHETYPE_LABELS: Record<Archetype, string> = {
  minimal: 'Minimal',
  classic: 'Classic',
  street: 'Street',
  romantic_boho: 'Romantic / Boho',
  sporty: 'Sporty',
  edgy: 'Edgy / Statement',
};

/**
 * Departments whose archetype imagery exists on disk today (womens, mens). `both`
 * and `gender_neutral` fall back to a merged deck at the UI layer — they are valid
 * user selections but not physical image folders.
 */
export const ARCHETYPE_IMAGE_DEPARTMENTS = ['womens', 'mens'] as const;
export type ArchetypeImageDepartment = (typeof ARCHETYPE_IMAGE_DEPARTMENTS)[number];
