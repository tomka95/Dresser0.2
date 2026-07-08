/**
 * Calendar API client — connect plumbing (start/status/disconnect) + live reads.
 *
 * Mirrors the Gmail client. The frontend never constructs the consent URL or
 * holds a client secret; it navigates to the URL the backend returns. Tokens are
 * never seen here. Calendar CONTENT is read live per request and never persisted
 * server-side.
 */
import { getAccessToken } from '@/lib/auth';

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

export interface CalendarConnectionStatus {
  connected: boolean;
  scope: string | null;
  connected_at: string | null;
}

export interface CalendarEvent {
  summary: string;
  start: string; // 'HH:MM' or 'all day'
  location: string | null;
}

export interface CalendarTodayResponse {
  connected: boolean;
  events: CalendarEvent[];
}

/** Begin the Calendar-connect OAuth flow (full-page redirect to Google). */
export async function startCalendarConnect(): Promise<void> {
  const token = await getAccessToken();
  if (!token) throw new Error('Not authenticated. Please sign in first.');

  const response = await fetch(`${API_BASE_URL}/calendar/oauth/start`, {
    method: 'GET',
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!response.ok) throw new Error('Could not start Calendar connection. Please try again.');

  const { url } = (await response.json()) as { url: string };
  if (!url) throw new Error('Server did not return a Calendar authorization URL.');
  window.location.href = url;
}

/** Read whether the current user has a usable Calendar connection. */
export async function fetchCalendarConnectionStatus(): Promise<CalendarConnectionStatus> {
  const token = await getAccessToken();
  if (!token) throw new Error('Not authenticated. Please sign in first.');

  const response = await fetch(`${API_BASE_URL}/calendar/oauth/status`, {
    method: 'GET',
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!response.ok) throw new Error('Failed to read Calendar connection status.');
  return response.json();
}

/** Revoke the Google grant AND wipe stored tokens. */
export async function disconnectCalendar(): Promise<void> {
  const token = await getAccessToken();
  if (!token) throw new Error('Not authenticated. Please sign in first.');

  const response = await fetch(`${API_BASE_URL}/calendar/oauth/disconnect`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!response.ok) throw new Error('Could not disconnect Calendar. Please try again.');
}

/** Today's upcoming events (live). Returns `{ connected:false }` on any failure. */
/**
 * Module-level stale-while-revalidate cache (survives client-side navigation,
 * resets on full reload). Shorter TTL than weather — a day's schedule can change.
 */
const CALENDAR_TTL_MS = 2 * 60 * 1000; // 2 min
let _calendarCache: { data: CalendarTodayResponse; ts: number } | null = null;

/** Last cached calendar, or null on a cold client. Synchronous — for instant paint. */
export function getCachedCalendarToday(): CalendarTodayResponse | null {
  return _calendarCache?.data ?? null;
}

/** True when the cache exists and is within TTL (skip the network entirely). */
export function isCalendarFresh(): boolean {
  return _calendarCache != null && Date.now() - _calendarCache.ts < CALENDAR_TTL_MS;
}

/** Today's upcoming events (live). Returns `{ connected:false }` on any failure.
 * Caches only CONNECTED results (the slow Google-hitting path); a not-connected
 * or transient-error result never overwrites a good cache. */
export async function getCalendarToday(): Promise<CalendarTodayResponse> {
  const token = await getAccessToken();
  if (!token) return { connected: false, events: [] };

  let result: CalendarTodayResponse;
  try {
    const response = await fetch(`${API_BASE_URL}/calendar/today`, {
      method: 'GET',
      headers: { Authorization: `Bearer ${token}` },
    });
    result = response.ok
      ? ((await response.json()) as CalendarTodayResponse)
      : { connected: false, events: [] };
  } catch {
    result = { connected: false, events: [] };
  }

  if (result.connected) {
    _calendarCache = { data: result, ts: Date.now() };
  }
  return result;
}
