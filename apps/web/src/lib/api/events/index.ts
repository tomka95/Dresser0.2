/**
 * Interaction telemetry client (Wave S0 Branch C).
 *
 * Batches client-side user actions and POSTs them to the FastAPI /events endpoint,
 * which writes them into style_events. Fire-and-forget: telemetry must NEVER block
 * or break the UI, so all failures are swallowed.
 *
 * The server sets user_id from the JWT — this client never sends it. We attach a
 * client-generated sessionId (stable per browser tab session) so the backend can
 * group a visit's events.
 */
import { getAccessToken } from '@/lib/auth';
import { API_BASE_URL } from '@/lib/api/base';

const SESSION_KEY = 'tailor_session_id';

const FLUSH_INTERVAL_MS = 2000;
const MAX_QUEUE = 50; // must stay <= backend EVENTS_MAX_BATCH

export interface EventInput {
  eventType: string;
  itemId?: string;
  entityType?: string;
  entityId?: string;
  source?: string;
  properties?: Record<string, unknown>;
}

type QueuedEvent = EventInput & { sessionId: string };

let queue: QueuedEvent[] = [];
let flushTimer: ReturnType<typeof setTimeout> | null = null;
let unloadHooked = false;

function isBrowser(): boolean {
  return typeof window !== 'undefined';
}

/** Stable per-tab-session UUID. Generated lazily; emits one session_start on creation. */
export function getSessionId(): string {
  if (!isBrowser()) return '00000000-0000-0000-0000-000000000000';
  let id = window.sessionStorage.getItem(SESSION_KEY);
  if (!id) {
    id =
      typeof crypto !== 'undefined' && 'randomUUID' in crypto
        ? crypto.randomUUID()
        : `${Date.now()}-${Math.random().toString(36).slice(2)}`;
    window.sessionStorage.setItem(SESSION_KEY, id);
  }
  return id;
}

async function flush(useKeepalive = false): Promise<void> {
  if (!queue.length) return;
  const batch = queue.slice(0, MAX_QUEUE);
  queue = queue.slice(MAX_QUEUE);

  let token: string | null = null;
  try {
    token = await getAccessToken();
  } catch {
    token = null;
  }
  if (!token) return; // not signed in — drop silently

  try {
    await fetch(`${API_BASE_URL}/events`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({ events: batch }),
      // keepalive lets the request survive a page unload (with the auth header,
      // unlike navigator.sendBeacon which cannot set Authorization).
      keepalive: useKeepalive,
    });
  } catch {
    // Network error — telemetry is best-effort; drop the batch.
  }

  // Anything still queued (over MAX_QUEUE) flushes on the next tick.
  if (queue.length) scheduleFlush();
}

function scheduleFlush(): void {
  if (flushTimer) return;
  flushTimer = setTimeout(() => {
    flushTimer = null;
    void flush();
  }, FLUSH_INTERVAL_MS);
}

function hookUnload(): void {
  if (unloadHooked || !isBrowser()) return;
  unloadHooked = true;
  // Flush on tab hide/close so a visit's tail events aren't lost.
  const onHide = () => {
    if (document.visibilityState === 'hidden') void flush(true);
  };
  document.addEventListener('visibilitychange', onHide);
  window.addEventListener('pagehide', () => void flush(true));
}

/** Queue one interaction event. Non-blocking; flushed in batches. */
export function logEvent(input: EventInput): void {
  if (!isBrowser()) return;
  hookUnload();
  queue.push({ ...input, sessionId: getSessionId() });
  if (queue.length >= MAX_QUEUE) {
    void flush();
  } else {
    scheduleFlush();
  }
}

/** Emit session_start once per tab session (idempotent via sessionStorage flag). */
export function startSession(): void {
  if (!isBrowser()) return;
  const flag = `${SESSION_KEY}_started`;
  if (window.sessionStorage.getItem(flag)) return;
  window.sessionStorage.setItem(flag, '1');
  logEvent({ eventType: 'session_start', source: 'system' });
}
