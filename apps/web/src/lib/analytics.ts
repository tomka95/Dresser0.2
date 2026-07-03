/**
 * Analytics wrapper for event tracking.
 *
 * Backed by the FastAPI /events endpoint (style_events). `track()` still logs to
 * console in dev; when its event name maps to a known taxonomy type it is ALSO
 * forwarded to the backend via the batching events client. Callers that need
 * typed refs (itemId/entityId/properties) should use `logEvent` directly.
 */
import { logEvent as sendEvent, startSession } from '@/lib/api/events';

export { logEvent, startSession, getSessionId } from '@/lib/api/events';

// Legacy free-form `track()` names that correspond 1:1 to a backend taxonomy type.
// Only these are forwarded to /events; other names stay console-only so we never
// POST an event the server would reject with a 422.
const FORWARDED_EVENTS: Record<string, string> = {
  outfit_shown: 'outfit_shown',
  outfit_suggestions_viewed: 'outfit_shown',
  outfit_liked: 'outfit_accept',
  outfit_unliked: 'outfit_reject',
};

export function track(event: string, props?: Record<string, any>): void {
  if (process.env.NODE_ENV === 'development') {
    console.log('[Analytics]', event, props || {});
  }
  const mapped = FORWARDED_EVENTS[event];
  if (mapped) {
    sendEvent({ eventType: mapped, source: 'system', properties: props });
  }
}

// Re-export so existing imports keep working while new code uses logEvent/startSession.
export { sendEvent };









