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

export default function OnboardingPage() {
  const { session, loading } = useRequireAuth();
  if (loading || !session) return null;
  return <OnboardingFlow />;
}
