'use client';

import { useEffect, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import { Check, ChevronLeft, RotateCw } from 'lucide-react';

import { Btn, M, SuccessPop, StateBlock } from '@/components/ds';
import { useOnboardingStore, ONBOARDING_STEPS } from '@/stores/useOnboardingStore';
import { seedOnboarding } from '@/lib/api/onboarding';
import { STEPS } from './steps';
import { ResumeCard } from './ResumeCard';

/**
 * OnboardingFlow — the 6-step container (§2). Its OWN full-screen flow: a
 * photographic backdrop + scrim (no AppShell, no bottom nav), the navigation
 * chrome (back · progress dots · skip), the current step's screen, and one pinned
 * CTA. Steps write staged answers to useOnboardingStore; NOTHING hits the server
 * until the final step, when the whole thing commits in ONE seedOnboarding() call.
 * onboarding_completed_at is stamped server-side only on that success — a failed or
 * abandoned flow leaves the flag unset, so the gate re-enters the user at step 1.
 *
 * On a successful commit we show a brief success state (O8) whose CTA routes home;
 * on a failed commit we keep the flow open with an error state (answers are kept
 * in memory, so the retry re-commits without re-asking).
 */
export function OnboardingFlow() {
  const router = useRouter();
  const step = useOnboardingStore((s) => s.step);
  const next = useOnboardingStore((s) => s.next);
  const back = useOnboardingStore((s) => s.back);
  const setCompleted = useOnboardingStore((s) => s.setCompleted);
  const reset = useOnboardingStore((s) => s.reset);

  // O9 — rehydrate any localStorage draft on mount, then decide whether to show the
  // resume card. `hydrated` gates the first paint so we never flash step 1 before a
  // saved draft has been read back in.
  const hydrated = useOnboardingStore((s) => s.hydrated);
  const resumable = useOnboardingStore((s) => s.resumable);
  const hydrateDraft = useOnboardingStore((s) => s.hydrateDraft);
  const clearResumable = useOnboardingStore((s) => s.clearResumable);
  const setStep = useOnboardingStore((s) => s.setStep);
  useEffect(() => {
    hydrateDraft();
  }, [hydrateDraft]);

  // G2a — returning from the onboarding Gmail OAuth (?gmail=connected). The connect ran
  // the background scan; the Gmail step is DONE. Skip the "Welcome back" resume interstitial
  // (that's for genuine cold returns only) and advance PAST the Gmail step to the next one,
  // so the user isn't looped back onto step 3 (the Gmail step). Read once, before paint.
  const returningFromGmail = useRef(
    typeof window !== 'undefined' &&
      new URLSearchParams(window.location.search).get('gmail') === 'connected',
  );
  useEffect(() => {
    if (!hydrated || !returningFromGmail.current) return;
    const gmailIdx = STEPS.findIndex((s) => s.key === 'gmail_scan');
    const nextStep = gmailIdx >= 0 ? Math.min(gmailIdx + 2, ONBOARDING_STEPS) : step;
    clearResumable();
    setStep(nextStep); // 1-based: the step AFTER gmail_scan
    returningFromGmail.current = false;
    // Strip the query so a refresh doesn't re-trigger the advance.
    router.replace('/onboarding');
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hydrated]);

  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // 'done' = commit succeeded; render the success state, then route home on tap.
  const [phase, setPhase] = useState<'flow' | 'done' | 'failed'>('flow');

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
      // Commit-first is load-bearing: the flag is set and answers committed BEFORE
      // any navigation, so the success CTA's router.replace can't strand the user.
      setPhase('done');
      setSubmitting(false);
    } catch (e) {
      // Keep onboarding open: the flag is unset, so the user can retry the commit.
      setError(e instanceof Error ? e.message : 'Something went wrong. Try again.');
      setPhase('failed');
      setSubmitting(false);
    }
  }

  function goHome() {
    reset();
    router.replace('/home');
  }

  function handlePrimary() {
    if (isLast) {
      void finish();
    } else {
      next();
    }
  }

  // Wait for the draft rehydration to run before the first paint so a returning
  // user never sees step 1 flash before their saved progress loads.
  if (!hydrated) {
    return <Backdrop />;
  }

  // ── O9 · Resume mid-flow — a saved draft exists; offer continue / start over ─
  // Suppressed on an in-flow Gmail-OAuth return (?gmail=connected): that's not a cold
  // return, and the effect above advances past the Gmail step (G2a). The interstitial is
  // for genuine cold returns only — gated on the absence of the ?gmail=connected signal.
  if (resumable && phase === 'flow' && !returningFromGmail.current) {
    return (
      <Backdrop>
        <ResumeCard
          step={step}
          onContinue={clearResumable}
          onStartOver={() => {
            reset(); // clears the draft + resumable, back to step 1
          }}
        />
      </Backdrop>
    );
  }

  // ── Completion states (O8) — success + commit-error ───────────────────────
  if (phase === 'done') {
    return (
      <Backdrop center>
        <StateBlock
          icon={<SuccessPop size={104} />}
          title="Your profile is set"
          sub="Tailor sharpens with every wear — your closet, fits, and taste are ready."
          cta={
            <Btn variant="primary" size="lg" fullWidth onClick={goHome}>
              Take me home
            </Btn>
          }
        />
      </Backdrop>
    );
  }

  if (phase === 'failed') {
    return (
      <Backdrop center>
        <StateBlock
          tone="danger"
          icon={<RotateCw size={30} />}
          title="Couldn't save just now"
          sub="Your answers are kept on this phone — nothing to redo. Retry, or continue anyway."
          cta={
            <Btn
              variant="primary"
              size="lg"
              fullWidth
              pending={submitting}
              icon={<RotateCw size={17} />}
              onClick={() => void finish()}
            >
              Retry now
            </Btn>
          }
          cta2={
            <Btn variant="ghost" size="md" onClick={goHome}>
              Continue anyway
            </Btn>
          }
        />
        {error ? (
          <p className="mt-3 text-center text-[12.5px]" style={{ color: 'var(--danger)' }}>
            {error}
          </p>
        ) : null}
      </Backdrop>
    );
  }

  const StepComponent = def.Component;

  return (
    <Backdrop>
      <div className="flex h-full flex-col">
        {/* O7 chrome — back · progress dots · skip */}
        <div className="relative z-[5] flex items-center justify-between" style={{ padding: '64px 20px 0' }}>
          <button
            type="button"
            onClick={back}
            disabled={step === 1 || submitting}
            aria-label="Back"
            className="flex items-center justify-center disabled:cursor-default"
            style={{
              width: 38,
              height: 38,
              borderRadius: 13,
              border: '1px solid rgba(255,255,255,0.13)',
              background: 'rgba(255,255,255,0.06)',
              color: step === 1 ? 'transparent' : '#fff',
            }}
          >
            <ChevronLeft size={19} />
          </button>

          <div
            className="flex items-center gap-[7px]"
            role="status"
            aria-label={`Step ${step} of ${ONBOARDING_STEPS}`}
          >
            {STEPS.map((s, i) => {
              const n = i + 1;
              return (
                <span
                  key={s.key}
                  style={{
                    width: n === step ? 22 : 6.5,
                    height: 6.5,
                    borderRadius: 4,
                    background:
                      n < step
                        ? 'rgba(75,226,214,0.55)'
                        : n === step
                          ? 'var(--mint)'
                          : 'rgba(255,255,255,0.18)',
                    boxShadow: n === step ? '0 0 10px rgba(75,226,214,0.5)' : 'none',
                    transition: 'all 300ms var(--ease-out)',
                  }}
                />
              );
            })}
          </div>

          {def.skippable && !isLast ? (
            <button
              type="button"
              onClick={next}
              disabled={submitting}
              className="text-right text-[13.5px] font-medium"
              style={{ width: 38, color: M.faint }}
            >
              Skip
            </button>
          ) : (
            <span style={{ width: 38 }} />
          )}
        </div>

        {/* Current step — scrolls; the footer CTA stays pinned */}
        <div className="relative z-[4] min-h-0 flex-1 overflow-y-auto" style={{ padding: '26px 22px 18px' }}>
          <StepComponent />
        </div>

        {/* Footer: inline error + primary CTA */}
        <div className="relative z-[5]" style={{ padding: '10px 22px 30px' }}>
          {error ? (
            <p className="mb-2.5 text-center text-[13px]" style={{ color: '#ff8f8f' }}>
              {error}
            </p>
          ) : null}
          <Btn
            variant="primary"
            size="lg"
            fullWidth
            disabled={!canAdvance || submitting}
            pending={submitting}
            onClick={handlePrimary}
          >
            {isLast ? 'Finish' : 'Continue'}
          </Btn>
        </div>
      </div>
    </Backdrop>
  );
}

/**
 * Backdrop — the standalone onboarding shell: a dimmed closet photo + scrim over
 * the app-bg fallback. `center` vertically centers its child (used by the
 * completion states); otherwise the child owns its own column layout.
 */
function Backdrop({ children, center = false }: { children?: React.ReactNode; center?: boolean }) {
  return (
    <div
      className="relative h-full min-h-full w-full overflow-hidden"
      style={{ background: 'var(--app-bg)' }}
    >
      {/* Background photo */}
      <div
        className="pointer-events-none absolute inset-0 z-0"
        style={{
          backgroundImage: "url('/auth/closet-bg.jpg')",
          backgroundSize: 'cover',
          backgroundPosition: 'center',
          opacity: 0.5,
        }}
        aria-hidden
      />
      {/* Scrim gradient */}
      <div
        className="pointer-events-none absolute inset-0 z-0"
        style={{ background: 'var(--grad-scrim)' }}
        aria-hidden
      />
      {/* Content */}
      <div
        className={
          center
            ? 'absolute inset-0 z-10 flex flex-col items-center justify-center px-6'
            : 'absolute inset-0 z-10'
        }
      >
        {children}
      </div>
    </div>
  );
}
