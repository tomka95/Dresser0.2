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
 * Usage:
 *   const { session, loading } = useRequireAuth();
 *   if (loading || !session) return null; // or a spinner
 */
import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import type { Session } from '@supabase/supabase-js';

import { getSession, onAuthStateChange } from '@/lib/auth';

export type AuthStatus = 'loading' | 'authenticated' | 'unauthenticated';

export function useRequireAuth(redirectTo: string = '/sign-in') {
  const router = useRouter();
  const [session, setSession] = useState<Session | null>(null);
  const [status, setStatus] = useState<AuthStatus>('loading');

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

  return { session, status, loading: status === 'loading' };
}
