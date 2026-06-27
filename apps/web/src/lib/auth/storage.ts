/**
 * @deprecated Legacy import path. Auth now lives in `@/lib/auth`, backed by
 * Supabase Auth (supabase-js manages the session/token — we no longer hand-store
 * a token in localStorage).
 *
 * This shim is kept only so any straggler imports of `@/lib/auth/storage` keep
 * resolving during the cutover. Prefer importing from `@/lib/auth` directly.
 *
 * Note the behavioral change: getAccessToken()/isAuthenticated() are now ASYNC
 * (they read the Supabase session). `clearAuth` maps to Supabase signOut().
 */
export {
  getAccessToken,
  isAuthenticated,
  signOut as clearAuth,
} from '@/lib/auth';
