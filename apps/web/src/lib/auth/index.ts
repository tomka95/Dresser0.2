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
function authCallbackUrl(): string | undefined {
  if (typeof window === 'undefined') return undefined;
  return `${window.location.origin}/auth/callback`;
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
      emailRedirectTo: authCallbackUrl(),
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

export async function signOut(): Promise<void> {
  const { error } = await getSupabaseClient().auth.signOut();
  if (error) throw new Error(error.message);
}

/** Where the password-reset email link returns to. */
function resetPasswordUrl(): string | undefined {
  if (typeof window === 'undefined') return undefined;
  return `${window.location.origin}/reset-password`;
}

/**
 * Send a password-reset email. Supabase emails a magic link that lands on
 * /reset-password with a recovery session, where updatePassword() finishes it.
 * Always resolves (we do not reveal whether the email exists) unless Supabase
 * itself errors.
 */
export async function requestPasswordReset(email: string): Promise<void> {
  const { error } = await getSupabaseClient().auth.resetPasswordForEmail(email, {
    redirectTo: resetPasswordUrl(),
  });
  if (error) throw new Error(error.message);
}

/**
 * Set a new password for the current (recovery) session. Reached from the email
 * link, where supabase-js has already exchanged the recovery token into a session.
 */
export async function updatePassword(newPassword: string): Promise<void> {
  const { error } = await getSupabaseClient().auth.updateUser({ password: newPassword });
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
