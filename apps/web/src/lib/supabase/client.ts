/**
 * Singleton Supabase BROWSER client (cookie-backed via @supabase/ssr).
 *
 * This is the only place the browser client is constructed. It reads the public
 * project URL + anon (publishable) key from NEXT_PUBLIC_ env vars — no secrets.
 *
 * Why @supabase/ssr (cookie storage) instead of the plain localStorage client:
 * the session is stored in cookies that BOTH the browser client and the server
 * (Route Handlers, middleware, Server Components) can read. That makes the session
 * survive client-side navigations and a hard reload, and lets the OAuth code be
 * exchanged server-side in app/auth/callback/route.ts. supabase-js still owns the
 * session lifecycle (refresh handled by middleware.ts) — we never hand-manage it.
 *
 * The PKCE code exchange is performed by the server Route Handler, so this client
 * does not need detectSessionInUrl.
 */
import { createBrowserClient } from '@supabase/ssr';

const SUPABASE_URL = process.env.NEXT_PUBLIC_SUPABASE_URL;
const SUPABASE_ANON_KEY = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;

type BrowserClient = ReturnType<typeof createBrowserClient>;

// Cache on globalThis so Fast Refresh / multiple imports reuse one client (and
// one cookie storage adapter) rather than creating multiple GoTrueClients.
const globalForSupabase = globalThis as unknown as {
  __tailorSupabase?: BrowserClient;
};

export function getSupabaseClient(): BrowserClient {
  if (!SUPABASE_URL || !SUPABASE_ANON_KEY) {
    throw new Error(
      'Supabase is not configured. Set NEXT_PUBLIC_SUPABASE_URL and ' +
        'NEXT_PUBLIC_SUPABASE_ANON_KEY (see apps/web/.env.local.example).'
    );
  }
  if (!globalForSupabase.__tailorSupabase) {
    globalForSupabase.__tailorSupabase = createBrowserClient(SUPABASE_URL, SUPABASE_ANON_KEY);
  }
  return globalForSupabase.__tailorSupabase;
}
