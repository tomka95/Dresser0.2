/**
 * Singleton Supabase browser client.
 *
 * This is the ONLY place the supabase-js client is constructed. It reads the
 * public project URL + anon (publishable) key from NEXT_PUBLIC_ env vars — no
 * secrets in code.
 *
 * Session management is delegated entirely to supabase-js:
 *   - persistSession    : it stores the session (localStorage by default) so it
 *                         survives reloads. We never hand-manage tokens.
 *   - autoRefreshToken  : it refreshes the access token before expiry.
 *   - detectSessionInUrl: it completes the OAuth redirect (auth-code/PKCE) by
 *                         reading the `?code=...` on /auth/callback and exchanging
 *                         it for a session.
 *   - flowType: 'pkce'  : modern, browser-safe OAuth (no client secret).
 *
 * SSR caveat (flagged for review): this is a browser-only client backed by
 * localStorage, matching the app's existing client-side auth model. Next.js
 * Server Components / middleware / Route Handlers cannot read a localStorage
 * session. If/when we need server-side auth (SSR data fetching as the user, or
 * middleware-level route protection), switch to @supabase/ssr with cookie
 * storage. Not required for this step.
 */
import { createClient, type SupabaseClient } from '@supabase/supabase-js';

const SUPABASE_URL = process.env.NEXT_PUBLIC_SUPABASE_URL;
const SUPABASE_ANON_KEY = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;

// Cache the client on globalThis so Fast Refresh / multiple imports don't create
// multiple GoTrueClient instances (which warns and can desync auth state).
const globalForSupabase = globalThis as unknown as {
  __tailorSupabase?: SupabaseClient;
};

export function getSupabaseClient(): SupabaseClient {
  if (!SUPABASE_URL || !SUPABASE_ANON_KEY) {
    throw new Error(
      'Supabase is not configured. Set NEXT_PUBLIC_SUPABASE_URL and ' +
        'NEXT_PUBLIC_SUPABASE_ANON_KEY (see apps/web/.env.local.example).'
    );
  }
  if (!globalForSupabase.__tailorSupabase) {
    globalForSupabase.__tailorSupabase = createClient(SUPABASE_URL, SUPABASE_ANON_KEY, {
      auth: {
        persistSession: true,
        autoRefreshToken: true,
        detectSessionInUrl: true,
        flowType: 'pkce',
      },
    });
  }
  return globalForSupabase.__tailorSupabase;
}
