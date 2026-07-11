/**
 * Outfits API client — the real Lookbook backend.
 *
 *   GET    /outfits             list saved outfits (chat saves, worn Today's
 *                               Looks, composer generates)
 *   POST   /outfits/generate    compose one outfit on demand (weather +
 *                               occasion + Style Profile, server-side)
 *   PUT    /outfits/{id}/like   like   (persisted server-side)
 *   DELETE /outfits/{id}/like   unlike
 *   DELETE /outfits/{id}        unsave
 *
 * The server sets user_id from the JWT; this client never sends it. A generate
 * that can't complete a look returns { sufficient: false, gaps } — the caller
 * renders the honest empty state, nothing is force-filled.
 */
import type { GenerateOutfitResult, OutfitSuggestion } from '@tailor/contracts';
import { API_BASE_URL } from '@/lib/api/base';
import { getAccessToken } from '@/lib/auth';

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
  if (status === 429) throw new Error('Give it a few seconds before generating again.');
  if (status >= 500) throw new Error('Something went wrong. Please try again.');
  throw new Error(typeof error.detail === 'string' ? error.detail : 'Failed to load outfits');
}

async function parseOrThrow<T>(response: Response): Promise<T> {
  if (!response.ok) throwFromResponse(response.status, await response.json().catch(() => ({})));
  return response.json() as Promise<T>;
}

/** The user's saved outfits, newest first. */
export async function listOutfits(limit = 50): Promise<OutfitSuggestion[]> {
  const response = await fetch(`${API_BASE_URL}/outfits?limit=${limit}`, {
    method: 'GET',
    headers: await authHeaders(false),
  });
  return parseOrThrow<OutfitSuggestion[]>(response);
}

export interface GenerateOptions {
  occasion?: string;
  /** Item ids already on screen — the composer reaches for different pieces. */
  excludeItemIds?: string[];
}

/** Compose one outfit on demand. Complete looks are persisted server-side and
 * come back with a real id; incomplete closets come back honest (sufficient:
 * false + the composer's gap list) with nothing persisted. */
export async function generateOutfit(
  options: GenerateOptions = {}
): Promise<GenerateOutfitResult> {
  const response = await fetch(`${API_BASE_URL}/outfits/generate`, {
    method: 'POST',
    headers: await authHeaders(true),
    body: JSON.stringify({
      occasion: options.occasion,
      excludeItemIds: options.excludeItemIds ?? [],
    }),
  });
  return parseOrThrow<GenerateOutfitResult>(response);
}

/** Persist the heart server-side. */
export async function setOutfitLiked(
  outfitId: string,
  liked: boolean
): Promise<{ ok: boolean; outfitId: string; liked: boolean }> {
  const response = await fetch(`${API_BASE_URL}/outfits/${outfitId}/like`, {
    method: liked ? 'PUT' : 'DELETE',
    headers: await authHeaders(false),
  });
  return parseOrThrow(response);
}

/** Remove a saved outfit from the lookbook. */
export async function unsaveOutfit(
  outfitId: string
): Promise<{ ok: boolean; outfitId: string }> {
  const response = await fetch(`${API_BASE_URL}/outfits/${outfitId}`, {
    method: 'DELETE',
    headers: await authHeaders(false),
  });
  return parseOrThrow(response);
}
