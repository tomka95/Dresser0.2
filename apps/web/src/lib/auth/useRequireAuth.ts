'use client';

/**
 * Client-side route guard hook.
 *
 * Gates a page on the Supabase session, distinguishing THREE states so that
 * cross-screen navigation never flashes the sign-in page while supabase-js is
 * still rehydrating the session from storage:
 *
 *   - 'loading'         : session not yet determined  -> render nothing/spinner,
 *                         DO NOT redirect.
 *   - 'authenticated'   : a session exists            -> render the page.
 *   - 'unauthenticated' : session resolved to null    -> redirect to `redirectTo`.
 *
 * The initial state is resolved authoritatively by awaiting getSession() on mount
 * (which waits for rehydration). The onAuthStateChange subscription keeps the
 * state live for sign-in/sign-out/token-refresh, but its INITIAL_SESSION event is
 * ignored — getSession() is the source of truth for the initial resolution, and
 * an early INITIAL_SESSION(null) must not trigger a premature redirect.
 *
 * ONBOARDING GATE (opts.requireOnboarded, Wave S1): when set, an authenticated
 * user is additionally gated on GET /onboarding/status. Until completion is known
 * the hook keeps `loading` true (so the page renders nothing — no flash of app
 * chrome), and a NOT-completed user is redirected to `/onboarding`. The result is
 * cached in useOnboardingStore so later navigations short-circuit the fetch, and a
 * status-fetch failure FAILS CLOSED (treated as not-onboarded) so there is no way
 * to land on an app page half-onboarded. The /onboarding route itself must NOT
 * pass this flag (it would self-redirect into a loop).
 *
 * Usage:
 *   const { session, loading } = useRequireAuth();                       // auth only
 *   const { session, loading } = useRequireAuth('/sign-in', { requireOnboarded: true });
 *   if (loading || !session) return null; // or a spinner
 */
import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import type { Session } from '@supabase/supabase-js';

import { getSession, onAuthStateChange } from '@/lib/auth';
import { getOnboardingStatus } from '@/lib/api/onboarding';
import { useOnboardingStore } from '@/stores/useOnboardingStore';

export type AuthStatus = 'loading' | 'authenticated' | 'unauthenticated';

export interface RequireAuthOptions {
  /** Also gate on onboarding completion; not-onboarded -> redirect to /onboarding. */
  requireOnboarded?: boolean;
  /** Where a not-onboarded user is sent. */
  onboardingRoute?: string;
}

type GateStatus = 'unknown' | 'checking' | 'onboarded' | 'not_onboarded';

export function useRequireAuth(
  redirectTo: string = '/sign-in',
  opts: RequireAuthOptions = {}
) {
  const { requireOnboarded = false, onboardingRoute = '/onboarding' } = opts;
  const router = useRouter();
  const [session, setSession] = useState<Session | null>(null);
  const [status, setStatus] = useState<AuthStatus>('loading');
  const [gate, setGate] = useState<GateStatus>('unknown');

  const completedCache = useOnboardingStore((s) => s.completed);
  const setCompletedCache = useOnboardingStore((s) => s.setCompleted);

  useEffect(() => {
    let active = true;

    // Authoritative initial resolution — getSession() awaits rehydration, so a
    // logged-in user resolves to 'authenticated', never a transient 'null'.
    getSession()
      .then((current) => {
        if (!active) return;
        setSession(current);
        setStatus(current ? 'authenticated' : 'unauthenticated');
      })
      .catch(() => {
        if (!active) return;
        setSession(null);
        setStatus('unauthenticated');
      });

    // Keep state live for subsequent auth changes. Ignore INITIAL_SESSION: it can
    // arrive (possibly null) before rehydration completes, and getSession() above
    // already owns the initial resolution.
    const subscription = onAuthStateChange((event, next) => {
      if (!active || event === 'INITIAL_SESSION') return;
      setSession(next);
      setStatus(next ? 'authenticated' : 'unauthenticated');
    });

    return () => {
      active = false;
      subscription.unsubscribe();
    };
  }, []);

  // Redirect ONLY once the session has definitively resolved to null. While
  // 'loading' we never redirect, so navigation between authed screens can't flash
  // the sign-in page.
  useEffect(() => {
    if (status === 'unauthenticated') {
      router.replace(redirectTo);
    }
  }, [status, router, redirectTo]);

  // Onboarding gate: once authenticated, resolve completion (cache-first) and
  // redirect a not-onboarded user out. Fails closed on any status-fetch error.
  useEffect(() => {
    if (!requireOnboarded || status !== 'authenticated') return;

    if (completedCache === true) {
      setGate('onboarded');
      return;
    }

    let active = true;
    setGate('checking');
    getOnboardingStatus()
      .then((res) => {
        if (!active) return;
        if (res.completed) {
          setCompletedCache(true);
          setGate('onboarded');
        } else {
          setGate('not_onboarded');
        }
      })
      .catch(() => {
        // Fail closed: a status we can't confirm must not let the user through.
        if (active) setGate('not_onboarded');
      });

    return () => {
      active = false;
    };
  }, [requireOnboarded, status, completedCache, setCompletedCache]);

  useEffect(() => {
    if (requireOnboarded && gate === 'not_onboarded') {
      router.replace(onboardingRoute);
    }
  }, [requireOnboarded, gate, router, onboardingRoute]);

  // `loading` stays true until BOTH auth AND (if required) onboarding resolve to a
  // renderable state, so a gated page renders nothing until it's safe to show.
  const onboardingResolved = !requireOnboarded || gate === 'onboarded';
  const loading = status === 'loading' || (status === 'authenticated' && !onboardingResolved);

  return { session, status, loading };
}
