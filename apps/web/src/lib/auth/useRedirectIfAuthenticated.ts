'use client';

/**
 * Inverse of useRequireAuth — for pages meant ONLY for signed-out users
 * (sign-in, sign-up, forgot-password). An already-signed-in visitor is bounced
 * to the app home instead of being shown a credential form they don't need.
 *
 * Session resolution mirrors useRequireAuth exactly (same single mechanism):
 * getSession() is awaited on mount so it resolves AFTER supabase-js rehydrates
 * from storage — a logged-in user is recognized on a cold load rather than
 * flashing the form. onAuthStateChange keeps it live (e.g. sign-in in another
 * tab), ignoring the pre-rehydration INITIAL_SESSION event.
 *
 * Destination is the app home (`/home`); /home's own onboarding gate then routes
 * a signed-in-but-not-onboarded user onward to /onboarding — we deliberately do
 * NOT duplicate that decision here.
 *
 * `checking` stays true until we've confirmed there is NO session (or the check
 * errored). The caller MUST render a loading state — not the form — while
 * `checking`, so a signed-in user never sees a flash of the auth form before the
 * redirect. Unlike useRequireAuth this FAILS OPEN: if the session can't be read
 * we show the form, because a logged-out user must always be able to reach it.
 */
import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';

import { getSession, onAuthStateChange } from '@/lib/auth';

export function useRedirectIfAuthenticated(to: string = '/home') {
  const router = useRouter();
  const [checking, setChecking] = useState(true);

  useEffect(() => {
    let active = true;

    getSession()
      .then((session) => {
        if (!active) return;
        if (session) {
          // Keep `checking` true so the loader stays up through the redirect —
          // the form must never paint for a signed-in user.
          router.replace(to);
        } else {
          setChecking(false);
        }
      })
      .catch(() => {
        // Fail OPEN: an unreadable session must not trap a logged-out user on a
        // spinner — let them see the form.
        if (active) setChecking(false);
      });

    const subscription = onAuthStateChange((event, session) => {
      if (!active || event === 'INITIAL_SESSION') return;
      if (session) router.replace(to);
    });

    return () => {
      active = false;
      subscription.unsubscribe();
    };
  }, [router, to]);

  return { checking };
}
