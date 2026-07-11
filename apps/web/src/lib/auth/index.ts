/**
 * Auth module — the app's single identity surface, backed by Supabase Auth.
 *
 * Replaces the old hand-rolled localStorage token (`storage.ts`). Tokens and
 * session lifecycle are owned by supabase-js (see lib/supabase/client.ts); this
 * module is a thin, typed facade over `supabase.auth` plus the provider seam.
 *
 * Exposes:
 *   - getSession() / getSessionUser() — current Supabase session / user
 *   - getAccessToken() — the Supabase access token for API Authorization headers
 *   - isAuthenticated()
 *   - signUpWithPassword() / signInWithPassword() — email + password
 *   - signInWithProvider(id) — OAuth (Google now; Apple via config later)
 *   - signOut()
 *   - onAuthStateChange() — subscribe to session changes
 *
 * NOTE: getAccessToken()/isAuthenticated() are async because reading the session
 * is async (supabase-js may refresh the token first).
 */
import type { Session, User, AuthChangeEvent, Subscription } from '@supabase/supabase-js';

import { getSupabaseClient } from '@/lib/supabase/client';
import { providerToSupabase, type AuthProviderId } from '@/config/authProviders';

/** Where OAuth + email-confirmation links return to (must be an allowed redirect URL). */
function authCallbackUrl(next?: string): string | undefined {
  if (typeof window === 'undefined') return undefined;
  const base = `${window.location.origin}/auth/callback`;
  return next ? `${base}?next=${encodeURIComponent(next)}` : base;
}

export async function getSession(): Promise<Session | null> {
  const { data } = await getSupabaseClient().auth.getSession();
  return data.session;
}

export async function getSessionUser(): Promise<User | null> {
  const { data } = await getSupabaseClient().auth.getUser();
  return data.user;
}

/** The Supabase access token, or null when signed out. Use for Bearer auth. */
export async function getAccessToken(): Promise<string | null> {
  const session = await getSession();
  return session?.access_token ?? null;
}

export async function isAuthenticated(): Promise<boolean> {
  return (await getSession()) !== null;
}

export interface SignUpParams {
  email: string;
  password: string;
  fullName?: string;
}

export interface SignUpOutcome {
  /** True when email confirmation is required (no active session was returned). */
  needsEmailConfirmation: boolean;
  user: User | null;
}

/**
 * Email + password sign-up. With email confirmation ON (the dashboard setting),
 * Supabase returns no session and emails a confirmation link; the caller should
 * show a "check your email" state. With confirmation OFF, a session is returned.
 */
export async function signUpWithPassword({
  email,
  password,
  fullName,
}: SignUpParams): Promise<SignUpOutcome> {
  const { data, error } = await getSupabaseClient().auth.signUp({
    email,
    password,
    options: {
      data: fullName ? { full_name: fullName } : undefined,
      // Land email confirmations on the celebratory /confirmed screen.
      emailRedirectTo: authCallbackUrl('/confirmed'),
    },
  });
  if (error) throw new Error(error.message);
  return { needsEmailConfirmation: !data.session, user: data.user };
}

export async function signInWithPassword(params: {
  email: string;
  password: string;
}): Promise<void> {
  const { error } = await getSupabaseClient().auth.signInWithPassword(params);
  if (error) throw new Error(error.message);
}

/**
 * Start an OAuth sign-in. Redirects the browser to the provider and back to
 * /auth/callback. Login only — we deliberately request NO Gmail scopes here;
 * gmail.readonly is a separate authorization handled by the Gmail-connect flow.
 */
export async function signInWithProvider(id: AuthProviderId): Promise<void> {
  const { error } = await getSupabaseClient().auth.signInWithOAuth({
    provider: providerToSupabase(id),
    options: { redirectTo: authCallbackUrl() },
  });
  if (error) throw new Error(error.message);
}

/** Re-send the sign-up confirmation email (the "Didn't get it? Resend" action). */
export async function resendSignUpEmail(email: string): Promise<void> {
  const { error } = await getSupabaseClient().auth.resend({
    type: 'signup',
    email,
    options: { emailRedirectTo: authCallbackUrl('/confirmed') },
  });
  if (error) throw new Error(error.message);
}

/**
 * Send a password-reset link. The link lands on /reset-password with a recovery
 * session, where updatePassword() completes the flow.
 */
export async function resetPasswordForEmail(email: string): Promise<void> {
  const redirectTo =
    typeof window === 'undefined' ? undefined : `${window.location.origin}/reset-password`;
  const { error } = await getSupabaseClient().auth.resetPasswordForEmail(email, { redirectTo });
  if (error) throw new Error(error.message);
}

/**
 * Verify the user's CURRENT password (SCRUM-75) WITHOUT disturbing the active
 * session. Supabase has no "check password" endpoint, so we sign in on a THROWAWAY
 * client configured to persist nothing (persistSession:false) — the app's real
 * cookie-backed session is never read or replaced, so this creates no second session
 * the user has to notice. Returns true iff the password is correct.
 *
 * The result is intentionally boolean: the caller shows a single generic "incorrect"
 * message and never surfaces GoTrue's raw error, so nothing leaks about account state
 * (the email is the signed-in user's own, so a failure only ever means "wrong password").
 * Failed attempts are rate-limited server-side by GoTrue's own sign-in throttling.
 */
export async function verifyCurrentPassword(email: string, password: string): Promise<boolean> {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const anon = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
  if (!url || !anon) throw new Error('Supabase is not configured.');

  const { createClient } = await import('@supabase/supabase-js');
  const probe = createClient(url, anon, {
    auth: { persistSession: false, autoRefreshToken: false, detectSessionInUrl: false },
  });
  try {
    const { error } = await probe.auth.signInWithPassword({ email, password });
    return !error;
  } finally {
    // The probe never persisted anything; sign it out to drop the in-memory session.
    await probe.auth.signOut().catch(() => {});
  }
}

/**
 * Set a new password for the signed-in user (normal session OR the recovery
 * session created by a reset link).
 *
 * NB: this does NOT verify the current password (Supabase can't, and this is also
 * reused by the reset-link recovery flow which has no current password). The change-
 * password screen gates on verifyCurrentPassword() before calling this.
 */
export async function updatePassword(password: string): Promise<void> {
  const { error } = await getSupabaseClient().auth.updateUser({ password });
  if (error) throw new Error(error.message);
}

/** Update profile metadata (currently the display/full name). */
export async function updateProfileName(fullName: string): Promise<void> {
  const { error } = await getSupabaseClient().auth.updateUser({ data: { full_name: fullName } });
  if (error) throw new Error(error.message);
}

export async function signOut(): Promise<void> {
  const { error } = await getSupabaseClient().auth.signOut();
  if (error) throw new Error(error.message);
}

/** Subscribe to auth state changes. Returns the supabase Subscription. */
export function onAuthStateChange(
  callback: (event: AuthChangeEvent, session: Session | null) => void
): Subscription {
  const {
    data: { subscription },
  } = getSupabaseClient().auth.onAuthStateChange(callback);
  return subscription;
}
