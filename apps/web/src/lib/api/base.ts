/**
 * The single source of truth for the backend API base URL.
 *
 * Every API client, route handler, and component in the web app builds its
 * request URLs from this constant — no other module constructs its own base.
 * It is env-driven so one build can point at localhost in dev, a deployed
 * backend in production, and the (embedded/remote) backend inside a Capacitor
 * shell, purely via NEXT_PUBLIC_API_URL at build time.
 *
 * GUARD: src/__tests__/apiBaseGuard.test.ts fails the suite if the literal
 * "localhost:8000" appears anywhere under apps/web/src outside THIS file — so a
 * new client can't quietly re-introduce a hard-coded base.
 */
export const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
