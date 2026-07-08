/**
 * Today's Look API client — GET /todays-look (+ /remix, /wear).
 *
 * One auto-composed outfit for the day, driven server-side by weather + calendar
 * + style profile and rendered as a single pure-white grid collage. The client
 * never sends location or event data; user_id is the JWT subject on the server.
 *
 * Self-fetch pattern mirrors lib/api/weather + lib/api/calendar: a module-level
 * stale-while-revalidate cache (NOT SWR) so Home re-mounts paint instantly.
 * Fail-soft: GET returns a starter payload rather than throwing, so the card
 * never needs a try/catch to render.
 */
import { getAccessToken } from '@/lib/auth';

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

export interface TodaysLookItem {
  id: string;
  name?: string | null;
  category?: string | null;
  imageUrl?: string | null;
  /** True when this item has a real, showable photo (else a placeholder tile). */
  hasImage?: boolean;
}

export interface TodaysLookResponse {
  /** 'normal' = a complete look (even if below the day's ideal formality);
   *  'starter' = no completable look at any formality (thin closet). */
  kind: 'normal' | 'starter';
  itemIds: string[];
  items: TodaysLookItem[];
  collageUrl?: string | null;
  title: string;
  caption: string;
  occasion?: string | null;
  /** 1 hot .. 3 cold. */
  warmth?: number | null;
  /** The formality the look was actually composed at (may be below the ideal). */
  formality?: number | null;
  note?: string | null;
  rationale?: string;
}

export interface WearAck {
  ok: boolean;
  outfitId: string;
  itemCount: number;
  idempotent: boolean;
}

const STARTER_FALLBACK: TodaysLookResponse = {
  kind: 'starter',
  itemIds: [],
  items: [],
  collageUrl: null,
  title: '',
  caption: '',
  occasion: null,
  warmth: null,
  formality: null,
  note: null,
  rationale: '',
};

/**
 * Module-level stale-while-revalidate cache (survives client-side navigation,
 * resets on full reload). 15 min — the look is stable for the day, and Remix /
 * Wear update the cache directly.
 */
const TODAYS_LOOK_TTL_MS = 15 * 60 * 1000;
let _cache: { data: TodaysLookResponse; ts: number } | null = null;

/** Last cached look, or null on a cold client. Synchronous — for instant paint. */
export function getCachedTodaysLook(): TodaysLookResponse | null {
  return _cache?.data ?? null;
}

/** True when the cache exists and is within TTL (skip the network entirely). */
export function isTodaysLookFresh(): boolean {
  return _cache != null && Date.now() - _cache.ts < TODAYS_LOOK_TTL_MS;
}

/** Overwrite the cache (used by remix so the swapped-in look survives re-mount). */
export function setCachedTodaysLook(data: TodaysLookResponse): void {
  _cache = { data, ts: Date.now() };
}

/** Fetch the day's look. Returns a starter payload on any failure (auth/network/
 * backend) so callers never need a try/catch to render. Caches only a real
 * look — a starter/error result never overwrites a previously-good cache. The
 * server itself half-day-caches the look, so this call is cheap to revalidate. */
export async function getTodaysLook(): Promise<TodaysLookResponse> {
  const token = await getAccessToken();
  if (!token) return STARTER_FALLBACK;

  let result: TodaysLookResponse;
  try {
    const response = await fetch(`${API_BASE_URL}/todays-look`, {
      method: 'GET',
      headers: { Authorization: `Bearer ${token}` },
    });
    result = response.ok
      ? ((await response.json()) as TodaysLookResponse)
      : STARTER_FALLBACK;
  } catch {
    result = STARTER_FALLBACK;
  }

  if (result.kind !== 'starter') {
    _cache = { data: result, ts: Date.now() };
  }
  return result;
}

/** Remix — an alternative look that excludes the currently-shown items. Throws
 * on failure (the caller keeps the current look and toasts). Updates the cache
 * on success so the swapped-in look persists across re-mounts. */
export async function remixTodaysLook(itemIds: string[]): Promise<TodaysLookResponse> {
  const token = await getAccessToken();
  if (!token) throw new Error('Not authenticated. Please sign in first.');

  const response = await fetch(`${API_BASE_URL}/todays-look/remix`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${token}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ itemIds }),
  });
  if (response.status === 429) throw new Error('Give it a few seconds before remixing again.');
  if (!response.ok) throw new Error('Could not remix your look. Please try again.');

  const data = (await response.json()) as TodaysLookResponse;
  if (data.kind !== 'starter') setCachedTodaysLook(data);
  return data;
}

/** "Wear this" — persist the shown look as a worn outfit. Idempotent per day. */
export async function wearTodaysLook(itemIds: string[]): Promise<WearAck> {
  const token = await getAccessToken();
  if (!token) throw new Error('Not authenticated. Please sign in first.');

  const response = await fetch(`${API_BASE_URL}/todays-look/wear`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${token}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ itemIds }),
  });
  if (!response.ok) throw new Error('Could not save this look. Please try again.');
  return response.json();
}
