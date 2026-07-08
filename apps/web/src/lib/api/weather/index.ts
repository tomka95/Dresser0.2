/**
 * Weather API client — GET /weather.
 *
 * Returns the authenticated user's current + today forecast and a derived warmth
 * band (1 hot .. 3 cold). Location is server-held (from onboarding); the client
 * never sends coordinates. Fail-soft: the backend returns 200 with
 * `available: false` when there's no saved location or the provider is down, so
 * the Home tile degrades quietly instead of erroring.
 */
import { getAccessToken } from '@/lib/auth';

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

export interface WeatherCurrent {
  temp_c: number;
  feels_like_c: number;
  condition: string;
  precip_mm: number;
  is_day: boolean;
}

export interface WeatherToday {
  high_c: number;
  low_c: number;
  condition: string;
  precip_chance_pct: number | null;
}

export interface WeatherResponse {
  available: boolean;
  reason?: 'no_location' | 'unavailable' | string | null;
  current?: WeatherCurrent | null;
  today?: WeatherToday | null;
  /** 1 hot .. 3 cold — matches the stylist's warmth scale. */
  warmth_band?: number | null;
  timezone?: string | null;
  as_of?: string | null;
}

/**
 * Module-level stale-while-revalidate cache (survives client-side navigation,
 * resets on full reload). Lets Home re-mounts render the tile instantly instead
 * of showing a skeleton + waiting on the network every time.
 */
const WEATHER_TTL_MS = 10 * 60 * 1000; // 10 min
let _weatherCache: { data: WeatherResponse; ts: number } | null = null;

/** Last cached weather, or null on a cold client. Synchronous — for instant paint. */
export function getCachedWeather(): WeatherResponse | null {
  return _weatherCache?.data ?? null;
}

/** True when the cache exists and is within TTL (skip the network entirely). */
export function isWeatherFresh(): boolean {
  return _weatherCache != null && Date.now() - _weatherCache.ts < WEATHER_TTL_MS;
}

/** Fetch the current user's weather. Returns `{ available: false }` on any
 * failure (auth/network/backend) so callers never need a try/catch to render.
 * Caches only STABLE results (available, or no_location) — a transient
 * 'unavailable' never overwrites a previously-good cache or pins a failure. */
export async function getWeather(): Promise<WeatherResponse> {
  const token = await getAccessToken();
  if (!token) return { available: false, reason: 'unavailable' };

  let result: WeatherResponse;
  try {
    const response = await fetch(`${API_BASE_URL}/weather`, {
      method: 'GET',
      headers: { Authorization: `Bearer ${token}` },
    });
    result = response.ok
      ? ((await response.json()) as WeatherResponse)
      : { available: false, reason: 'unavailable' };
  } catch {
    result = { available: false, reason: 'unavailable' };
  }

  if (result.available || result.reason === 'no_location') {
    _weatherCache = { data: result, ts: Date.now() };
  }
  return result;
}
