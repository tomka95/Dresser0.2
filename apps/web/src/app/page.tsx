'use client';

/**
 * Root route (`/`) — the session-aware cold-start entry.
 *
 * This is a CLIENT component on purpose: the Supabase session lives in the
 * browser (supabase-js storage) and every gate in the app resolves it
 * client-side via useRequireAuth. Reusing that same hook here keeps ONE auth +
 * onboarding decision mechanism, and works identically in a deployed web build
 * and inside a static Capacitor shell (no per-request server needed).
 *
 * useRequireAuth('/sign-up', { requireOnboarded: true }) resolves to:
 *   - no session            → it redirects to /sign-up   (unchanged cold-start)
 *   - session, not onboarded → it redirects to /onboarding
 *   - session, onboarded     → returns the session; we send the user to /home
 *
 * A splash renders until one of those fires, so there's never a flash of the
 * wrong screen on a cold load.
 */
import { useEffect } from 'react';
import { useRouter } from 'next/navigation';

import { useRequireAuth } from '@/lib/auth/useRequireAuth';
import { Splash } from '@/components/ds';

export default function RootPage() {
  const router = useRouter();
  const { session, loading } = useRequireAuth('/sign-up', { requireOnboarded: true });

  useEffect(() => {
    // Only the authenticated + onboarded case falls through to here; the hook
    // owns the other two redirects.
    if (!loading && session) router.replace('/home');
  }, [loading, session, router]);

  return (
    <div className="relative h-full min-h-full w-full" style={{ background: 'var(--app-bg)' }}>
      <Splash />
    </div>
  );
}
