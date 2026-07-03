'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { ChevronLeft } from 'lucide-react';

import { DSButton } from '@/components/ds';
import { AppShell } from '@/components/layout/AppShell';
import { useOnboardingStore, ONBOARDING_STEPS } from '@/stores/useOnboardingStore';
import { seedOnboarding } from '@/lib/api/onboarding';
import { STEPS } from './steps';

/**
 * OnboardingFlow — the 6-step container. Owns the navigation chrome (progress
 * dots, back, skip, Continue/Finish) and renders the current step's screen from
 * the STEPS registry. Steps write staged answers to useOnboardingStore; NOTHING
 * hits the server until the final step, when the whole thing commits in ONE
 * seedOnboarding() call. onboarding_completed_at is stamped server-side only on
 * that success — a failed or abandoned flow leaves the flag unset, so the gate
 * re-enters the user at step 1.
 */
export function OnboardingFlow() {
  const router = useRouter();
  const step = useOnboardingStore((s) => s.step);
  const next = useOnboardingStore((s) => s.next);
  const back = useOnboardingStore((s) => s.back);
  const setCompleted = useOnboardingStore((s) => s.setCompleted);
  const reset = useOnboardingStore((s) => s.reset);

  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Subscribe to the whole store so the Continue enabled-state reacts to any
  // staged answer the current step writes (isComplete reads arbitrary fields).
  const state = useOnboardingStore();

  const def = STEPS[step - 1];
  const canAdvance = def.skippable || def.isComplete(state);
  const isLast = step === ONBOARDING_STEPS;

  async function finish() {
    setError(null);
    setSubmitting(true);
    try {
      const payload = useOnboardingStore.getState().buildSeedPayload();
      await seedOnboarding(payload);
      setCompleted(true); // cache so the gate short-circuits on the way to /home
      reset();
      router.replace('/home');
    } catch (e) {
      // Keep onboarding open: the flag is unset, so the user can retry the commit.
      setError(e instanceof Error ? e.message : 'Something went wrong. Try again.');
      setSubmitting(false);
    }
  }

  function handlePrimary() {
    if (isLast) {
      void finish();
    } else {
      next();
    }
  }

  const StepComponent = def.Component;

  return (
    <AppShell scroll={false} contentClassName="flex flex-col px-6 pb-6 pt-4">
      {/* Top chrome: back + progress dots + skip */}
      <div className="mb-6 flex items-center justify-between">
        <button
          type="button"
          onClick={back}
          disabled={step === 1 || submitting}
          aria-label="Back"
          className="flex h-8 w-8 items-center justify-center rounded-full text-white/80 disabled:opacity-0"
          style={{ background: 'rgba(255,255,255,0.06)' }}
        >
          <ChevronLeft size={20} />
        </button>

        <div className="flex items-center gap-1.5" aria-label={`Step ${step} of ${ONBOARDING_STEPS}`}>
          {STEPS.map((s, i) => (
            <span
              key={s.key}
              className="h-1.5 rounded-full transition-all"
              style={{
                width: i + 1 === step ? 20 : 6,
                background: i + 1 <= step ? 'var(--mint)' : 'rgba(255,255,255,0.22)',
              }}
            />
          ))}
        </div>

        {def.skippable && !isLast ? (
          <button
            type="button"
            onClick={next}
            disabled={submitting}
            className="text-[14px] font-medium text-white/55"
          >
            Skip
          </button>
        ) : (
          <span className="w-8" />
        )}
      </div>

      {/* Current step */}
      <StepComponent />

      {/* Footer: error + primary CTA */}
      <div className="mt-4">
        {error ? (
          <p className="mb-3 text-center text-[13px] text-[#ff8f8f]">{error}</p>
        ) : null}
        <DSButton
          variant="light"
          fullWidth
          pill
          disabled={!canAdvance || submitting}
          onClick={handlePrimary}
        >
          {isLast ? (submitting ? 'Finishing…' : 'Finish') : 'Continue'}
        </DSButton>
      </div>
    </AppShell>
  );
}
