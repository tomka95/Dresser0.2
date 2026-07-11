/**
 * Style Profile API — GET/PATCH /profile/style.
 *
 * Surfaces the server-side "brain" (style_profiles facts + distilled narrative,
 * style_preferences learned tastes) to the My Style Profile screen, and lets the
 * user correct it. Facts are the single source of truth for sizes; the settings
 * sizes screen reads/writes them through here (no more localStorage divergence).
 */
import type { SizeProfile, FitPreferences } from '@tailor/contracts';
import { API_BASE_URL } from '@/lib/api/base';
import { getAccessToken } from '@/lib/auth';

/** Whitelisted facts the screen renders/edits (server drops everything else). */
export interface StyleFacts {
  sizes?: SizeProfile;
  fits?: FitPreferences;
  fit_preference?: string;
  department?: string;
  occasions?: string[];
}

/** One learned preference, with a human explanation derived from its evidence. */
export interface LearnedPreference {
  dimension: string;
  value: Record<string, unknown>;
  polarity: 'like' | 'dislike' | 'neutral' | null;
  confidence: number | null;
  evidenceCount: number;
  source: string | null;
  userEdited: boolean;
  lastReinforcedAt: string | null;
  explanation: string;
}

export interface StyleProfile {
  facts: StyleFacts;
  narrative: string | null;
  summary: string | null;
  onboardingCompletedAt: string | null;
  version: number;
  preferences: LearnedPreference[];
}

/** A single preference change: an override (polarity/value) or a delete tombstone. */
export interface PreferenceEdit {
  dimension: string;
  polarity?: 'like' | 'dislike' | 'neutral' | null;
  value?: Record<string, unknown>;
  delete?: boolean;
}

export interface StyleProfilePatch {
  facts?: Partial<StyleFacts>;
  preferences?: PreferenceEdit[];
}

async function authHeaders(json: boolean): Promise<Record<string, string>> {
  const token = await getAccessToken();
  if (!token) throw new Error('Not authenticated. Please sign in first.');
  const h: Record<string, string> = { Authorization: `Bearer ${token}` };
  if (json) h['Content-Type'] = 'application/json';
  return h;
}

function throwFromResponse(status: number, error: { detail?: unknown }): never {
  if (Array.isArray(error.detail)) {
    throw new Error(error.detail.map((e: { msg?: string }) => e.msg).join(', '));
  }
  if (status === 401 || status === 403) throw new Error('Not authenticated. Please sign in first.');
  if (status >= 500) throw new Error('Something went wrong. Please try again.');
  throw new Error(typeof error.detail === 'string' ? error.detail : 'Failed to load style profile');
}

export async function getStyleProfile(): Promise<StyleProfile> {
  const response = await fetch(`${API_BASE_URL}/profile/style`, {
    method: 'GET',
    headers: await authHeaders(false),
  });
  if (!response.ok) throwFromResponse(response.status, await response.json().catch(() => ({})));
  return response.json();
}

export async function patchStyleProfile(patch: StyleProfilePatch): Promise<StyleProfile> {
  const response = await fetch(`${API_BASE_URL}/profile/style`, {
    method: 'PATCH',
    headers: await authHeaders(true),
    body: JSON.stringify(patch),
  });
  if (!response.ok) throwFromResponse(response.status, await response.json().catch(() => ({})));
  return response.json();
}
