'use client';

import React from 'react';
import { Check } from 'lucide-react';
import { DEPARTMENT_LABELS } from '@tailor/contracts';

import { Btn, M } from '@/components/ds';
import { useOnboardingStore, ONBOARDING_STEPS } from '@/stores/useOnboardingStore';
import { STEPS } from './steps';

/**
 * ResumeCard — the O9 "pick up where you left off" screen (§2 · O9).
 *
 * Shown on re-entry when a mid-flow draft was rehydrated from localStorage. It
 * mirrors the onboarding chrome (progress dots at the saved step, no back/skip) and
 * summarizes each of the six steps with a done marker and a short value read from
 * the real staged answers — so the card reflects the user's actual saved progress,
 * not a mock. Continue resumes exactly where they were; Start over wipes the draft.
 */
export function ResumeCard({
  step,
  onContinue,
  onStartOver,
}: {
  step: number;
  onContinue: () => void;
  onStartOver: () => void;
}) {
  const state = useOnboardingStore();
  const rows = STEPS.map((def, i) => {
    const n = i + 1;
    // A step is "done" once its answer predicate is satisfied OR the user has
    // already advanced past it (skippable steps count as done once left behind).
    const done = def.isComplete(state) || n < step;
    return { key: def.key, title: def.title, done, value: summarize(def.key, state) };
  });

  return (
    <div className="flex h-full flex-col">
      {/* Chrome — dots pinned to the saved step; back + skip intentionally hidden. */}
      <div
        className="relative z-[5] flex items-center justify-between"
        style={{ padding: '64px 20px 0' }}
      >
        <span style={{ width: 38 }} aria-hidden />
        <div
          className="flex items-center gap-[7px]"
          role="status"
          aria-label={`Resuming at step ${step} of ${ONBOARDING_STEPS}`}
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
                }}
              />
            );
          })}
        </div>
        <span style={{ width: 38 }} aria-hidden />
      </div>

      {/* Body */}
      <div className="relative z-[4] min-h-0 flex-1 overflow-y-auto" style={{ padding: '26px 22px 18px' }}>
        <h1
          className="m-0 text-[27px] font-bold leading-[1.15]"
          style={{ color: '#fff', letterSpacing: '-0.7px' }}
        >
          Welcome back
        </h1>
        <p className="m-0 mt-2 max-w-[300px] text-[14.5px] leading-relaxed" style={{ color: M.faint }}>
          Pick up where you left off — step {step} of {ONBOARDING_STEPS}. Your answers are saved on
          this device.
        </p>

        <div className="mt-6" style={{ ...M.glass(24), padding: 20 }}>
          {rows.map((r, i) => (
            <div
              key={r.key}
              className="flex items-center gap-3"
              style={{
                padding: '10.5px 0',
                borderBottom: i < rows.length - 1 ? '1px solid rgba(255,255,255,0.07)' : 'none',
              }}
            >
              <span
                className="flex shrink-0 items-center justify-center rounded-full text-[10.5px] font-bold"
                style={{
                  width: 24,
                  height: 24,
                  background: r.done ? 'rgba(75,226,214,0.15)' : 'rgba(255,255,255,0.07)',
                  border: r.done
                    ? '1px solid rgba(75,226,214,0.4)'
                    : '1px solid rgba(255,255,255,0.14)',
                  color: r.done ? 'var(--mint)' : M.ghost,
                }}
                aria-hidden
              >
                {r.done ? <Check size={12} strokeWidth={3} /> : i + 1}
              </span>
              <span
                className="flex-1 text-[14px]"
                style={{ color: r.done ? '#fff' : M.faint, fontWeight: r.done ? 550 : 450 }}
              >
                {r.title}
              </span>
              <span className="text-[12px]" style={{ color: r.done ? M.faint : M.ghost }}>
                {r.value}
              </span>
            </div>
          ))}
        </div>

        <div className="mt-4 text-center">
          <button
            type="button"
            onClick={onStartOver}
            className="text-[12.5px]"
            style={{ color: M.ghost }}
          >
            Start over instead
          </button>
        </div>
      </div>

      {/* Pinned CTA */}
      <div className="relative z-[5]" style={{ padding: '10px 22px 30px' }}>
        <Btn variant="primary" size="lg" fullWidth onClick={onContinue}>
          Pick up at step {step}
        </Btn>
      </div>
    </div>
  );
}

/** One short read-out per step, from the real staged answers. "—" when empty. */
function summarize(
  key: string,
  s: ReturnType<typeof useOnboardingStore.getState>,
): string {
  switch (key) {
    case 'departments':
      return s.department ? DEPARTMENT_LABELS[s.department] : '—';
    case 'sizes': {
      const parts: string[] = [];
      if (s.sizes.top) parts.push(String(s.sizes.top));
      if (s.sizes.bottom) {
        parts.push(
          s.sizes.bottom.system === 'letter'
            ? String(s.sizes.bottom.value)
            : `W${s.sizes.bottom.waist}`,
        );
      }
      if (s.sizes.shoe) parts.push(`${s.sizes.shoe.system} ${s.sizes.shoe.value}`);
      return parts.length ? parts.join(' · ') : '—';
    }
    case 'fits': {
      const n = [s.fits.top, s.fits.bottom].filter((v) => v !== undefined).length;
      return n ? `${n} set` : '—';
    }
    case 'taste':
      return s.tasteSwipes.length ? `${s.tasteSwipes.length} swiped` : '—';
    case 'occasions':
      return s.occasions.length ? `${s.occasions.length} picked` : '—';
    case 'weather':
      return s.location ? 'Location set' : '—';
    default:
      return '—';
  }
}
