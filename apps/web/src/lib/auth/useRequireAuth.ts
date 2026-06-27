'use client';

/**
 * Client-side route guard hook.
 *
 * Gates a page on the presence of a Supabase session, replacing the old
 * localStorage isAuthenticated() check. While the session is being resolved it
 * returns { loading: true }; once resolved, if there is no session it redirects
 * to `redirectTo`. It also reacts to live auth changes (e.g. sign-out in another
 * tab) via onAuthStateChange.
 *
 * Usage:
 *   const { session, loading } = useRequireAuth();
 *   if (loading || !session) return null; // or a spinner
 */
import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import type { Session } from '@supabase/supabase-js';

import { getSession, onAuthStateChange } from '@/lib/auth';

export function useRequireAuth(redirectTo: string = '/sign-in') {
  const router = useRouter();
  const [session, setSession] = useState<Session | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;

    getSession()
      .then((current) => {
        if (!active) return;
        setSession(current);
        setLoading(false);
        if (!current) router.replace(redirectTo);
      })
      .catch(() => {
        if (!active) return;
        setSession(null);
        setLoading(false);
        router.replace(redirectTo);
      });

    const subscription = onAuthStateChange((_event, next) => {
      if (!active) return;
      setSession(next);
      if (!next) router.replace(redirectTo);
    });

    return () => {
      active = false;
      subscription.unsubscribe();
    };
  }, [router, redirectTo]);

  return { session, loading };
}
