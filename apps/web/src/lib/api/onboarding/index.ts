/**
 * Onboarding API client (Wave S1).
 *
 * Wraps the two FastAPI endpoints the tap-only onboarding needs:
 *   - POST /onboarding/seed   — commit the staged answers in ONE call.
 *   - GET  /onboarding/status — {completed} for the completion gate.
 *
 * The server derives user_id from the JWT — this client never sends it, and NO
 * profile data ever travels in a URL param (bodies only). seed() throws on a
 * non-2xx so callers can keep onboarding open (flag stays unset) and let the user
 * retry; a failed seed must never strand a half-onboarded user past the gate.
 */
import type { PreferenceDimension, Polarity } from '@tailor/contracts';
import { API_BASE_URL } from '@/lib/api/base';

import { getAccessToken } from '@/lib/auth';

/** One structured preference row (dimension is the fixed shared vocabulary). */
export interface OnboardingPreference {
  dimension: PreferenceDimension;
  value?: Record<string, unknown>;
  polarity?: Polarity;
  /** Server clamps into the onboarding band regardless — sent only as a hint. */
  confidence?: number;
}

/** One raw signal (e.g. a taste-deck swipe). item/event refs are never sent. */
export interface OnboardingSignal {
  signalType: string;
  key?: string;
  value?: Record<string, unknown>;
  polarity?: Polarity;
  weight?: number;
}

/** The full seed body — every part optional (screens are skippable). */
export interface OnboardingSeedPayload {
  facts?: Record<string, unknown>;
  preferences?: OnboardingPreference[];
  signals?: OnboardingSignal[];
}

export interface OnboardingSeedAck {
  profileId: string;
  preferencesUpserted: number;
  signalsInserted: number;
}

export interface OnboardingStatus {
  completed: boolean;
}

async function authHeader(): Promise<Record<string, string>> {
  const token = await getAccessToken();
  if (!token) throw new Error('Not authenticated. Please sign in first.');
  return { Authorization: `Bearer ${token}` };
}

/**
 * Commit the onboarding answers. Idempotent server-side (re-run never 409s), so a
 * retry after a transient failure is safe. Throws on a non-2xx response.
 */
export async function seedOnboarding(
  payload: OnboardingSeedPayload
): Promise<OnboardingSeedAck> {
  const res = await fetch(`${API_BASE_URL}/onboarding/seed`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...(await authHeader()) },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(typeof err.detail === 'string' ? err.detail : 'Failed to seed onboarding');
  }
  return res.json();
}

/** Read the completion flag for the gate. Throws on a non-2xx (callers fail closed). */
export async function getOnboardingStatus(): Promise<OnboardingStatus> {
  const res = await fetch(`${API_BASE_URL}/onboarding/status`, {
    method: 'GET',
    headers: await authHeader(),
  });
  if (!res.ok) throw new Error('Failed to fetch onboarding status');
  return res.json();
}
