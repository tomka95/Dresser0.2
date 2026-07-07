'use client';

/**
 * /onboarding — the 6-screen tap-only onboarding.
 *
 * Auth-gated (a session is required) but NOT onboarding-gated: passing
 * requireOnboarded here would self-redirect into a loop. A user only reaches this
 * route because the completion gate on the app pages sent them here (or a fresh
 * signup landed here from /confirmed); the flow commits once and routes to /home.
 */
import { useRequireAuth } from '@/lib/auth/useRequireAuth';
import { OnboardingFlow } from '@/components/onboarding/OnboardingFlow';
import { OnboardingSkeleton } from '@/components/onboarding/OnboardingSkeleton';

export default function OnboardingPage() {
  const { session, loading } = useRequireAuth();
  // O10 — while the auth gate resolves, show the onboarding skeleton instead of a
  // blank page. Fail-closed is preserved: once resolved to no session the hook has
  // already fired a redirect to /sign-in, and we render nothing in that beat.
  if (loading) return <OnboardingSkeleton />;
  if (!session) return null;
  return <OnboardingFlow />;
}
