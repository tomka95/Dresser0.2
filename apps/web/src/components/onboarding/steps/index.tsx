'use client';

import React from 'react';
import {
  DEPARTMENTS,
  DEPARTMENT_LABELS,
  ARCHETYPES,
  ARCHETYPE_LABELS,
  LETTER_SIZES,
} from '@tailor/contracts';

import { useOnboardingStore } from '@/stores/useOnboardingStore';
import { OnboardingStep } from '../OnboardingStep';

/**
 * Step registry for the onboarding flow.
 *
 * Each entry is ONE screen. The `Component` here is a lightweight STUB that wires
 * the onboarding store end-to-end so the shell is navigable today; each screen
 * branch replaces its stub with the real UI (same store setters, same isComplete
 * contract). `isComplete(state)` gates the Continue button; `skippable` lets a user
 * advance without answering (Continue stays enabled, no value written).
 */
export interface StepDef {
  key: string;
  title: string;
  skippable: boolean;
  Component: React.FC;
  /** True when the step has enough staged data to advance. */
  isComplete: (s: ReturnType<typeof useOnboardingStore.getState>) => boolean;
}

// --- shared stub controls ----------------------------------------------------
function Pill({
  active,
  onClick,
  children,
}: {
  active?: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="rounded-full border px-4 py-2 text-[14px] font-medium transition"
      style={{
        borderColor: active ? 'var(--mint)' : 'rgba(255,255,255,0.18)',
        background: active ? 'rgba(75,226,214,0.16)' : 'rgba(255,255,255,0.04)',
        color: active ? 'var(--mint)' : 'rgba(255,255,255,0.85)',
      }}
    >
      {children}
    </button>
  );
}

function StubNote({ branch }: { branch: string }) {
  return (
    <p className="mt-auto pt-6 text-[12px] italic text-white/35">
      Stub — real UI lands in {branch}.
    </p>
  );
}

// --- step 1: departments -----------------------------------------------------
const DepartmentsStub: React.FC = () => {
  const department = useOnboardingStore((s) => s.department);
  const setDepartment = useOnboardingStore((s) => s.setDepartment);
  return (
    <OnboardingStep title="Who are we styling?" subtitle="Pick what you shop for.">
      <div className="flex flex-wrap gap-2">
        {DEPARTMENTS.map((d) => (
          <Pill key={d} active={department === d} onClick={() => setDepartment(d)}>
            {DEPARTMENT_LABELS[d]}
          </Pill>
        ))}
      </div>
      <StubNote branch="s1-onboarding-screens-1-3" />
    </OnboardingStep>
  );
};

// --- step 2: sizes -----------------------------------------------------------
const SizesStub: React.FC = () => {
  const top = useOnboardingStore((s) => s.sizes.top);
  const setSize = useOnboardingStore((s) => s.setSize);
  return (
    <OnboardingStep title="Your sizes" subtitle="We'll tune fit to these.">
      <div className="flex flex-wrap gap-2">
        {LETTER_SIZES.map((sz) => (
          <Pill key={sz} active={top === sz} onClick={() => setSize('top', sz)}>
            {sz}
          </Pill>
        ))}
      </div>
      <StubNote branch="s1-onboarding-screens-1-3" />
    </OnboardingStep>
  );
};

// --- step 3: fit sliders -----------------------------------------------------
const FitsStub: React.FC = () => {
  const fitTop = useOnboardingStore((s) => s.fits.top);
  const setFit = useOnboardingStore((s) => s.setFit);
  return (
    <OnboardingStep title="How do you like it to fit?" subtitle="Fitted to oversized.">
      <div className="flex flex-wrap gap-2">
        {[1, 2, 3, 4, 5].map((n) => (
          <Pill key={n} active={fitTop === n} onClick={() => setFit('top', n)}>
            {n}
          </Pill>
        ))}
      </div>
      <StubNote branch="s1-onboarding-screens-1-3" />
    </OnboardingStep>
  );
};

// --- step 4: taste deck ------------------------------------------------------
const TasteStub: React.FC = () => {
  const swipes = useOnboardingStore((s) => s.tasteSwipes);
  const addSwipe = useOnboardingStore((s) => s.addSwipe);
  return (
    <OnboardingStep title="What's your taste?" subtitle="Like or pass — tap a few.">
      <div className="flex flex-col gap-2">
        {ARCHETYPES.map((a) => {
          const swipe = swipes.find((t) => t.archetype === a);
          return (
            <div key={a} className="flex items-center justify-between gap-2">
              <span className="text-[14px] text-white/80">{ARCHETYPE_LABELS[a]}</span>
              <div className="flex gap-2">
                <Pill active={swipe?.liked === false} onClick={() => addSwipe({ archetype: a, liked: false })}>
                  Pass
                </Pill>
                <Pill active={swipe?.liked === true} onClick={() => addSwipe({ archetype: a, liked: true })}>
                  Like
                </Pill>
              </div>
            </div>
          );
        })}
      </div>
      <StubNote branch="s1-onboarding-taste-deck" />
    </OnboardingStep>
  );
};

// --- step 5: occasions -------------------------------------------------------
const OCCASION_OPTIONS = ['work', 'casual', 'going_out', 'formal', 'active', 'travel'];
const OccasionsStub: React.FC = () => {
  const occasions = useOnboardingStore((s) => s.occasions);
  const toggleOccasion = useOnboardingStore((s) => s.toggleOccasion);
  return (
    <OnboardingStep title="What do you dress for?" subtitle="Pick all that apply.">
      <div className="flex flex-wrap gap-2">
        {OCCASION_OPTIONS.map((o) => (
          <Pill key={o} active={occasions.includes(o)} onClick={() => toggleOccasion(o)}>
            {o.replace('_', ' ')}
          </Pill>
        ))}
      </div>
      <StubNote branch="s1-onboarding-screens-5-6" />
    </OnboardingStep>
  );
};

// --- step 6: weather + closet seed ------------------------------------------
const WeatherStub: React.FC = () => {
  const location = useOnboardingStore((s) => s.location);
  const setLocation = useOnboardingStore((s) => s.setLocation);
  const requestLocation = () => {
    if (typeof navigator === 'undefined' || !navigator.geolocation) return;
    navigator.geolocation.getCurrentPosition(
      (pos) => setLocation({ lat: pos.coords.latitude, lon: pos.coords.longitude }),
      () => {
        /* denied — screen 6 is skippable; closet seed handoff is a separate branch */
      }
    );
  };
  return (
    <OnboardingStep title="Dress for your weather" subtitle="Allow location for daily forecasts.">
      <div className="flex flex-col gap-2">
        <Pill active={!!location} onClick={requestLocation}>
          {location ? 'Location shared' : 'Allow location'}
        </Pill>
      </div>
      <StubNote branch="s1-onboarding-screens-5-6" />
    </OnboardingStep>
  );
};

export const STEPS: StepDef[] = [
  { key: 'departments', title: 'Departments', skippable: false, Component: DepartmentsStub, isComplete: (s) => !!s.department },
  { key: 'sizes', title: 'Sizes', skippable: false, Component: SizesStub, isComplete: (s) => Object.keys(s.sizes).length > 0 },
  { key: 'fits', title: 'Fit', skippable: true, Component: FitsStub, isComplete: (s) => Object.keys(s.fits).length > 0 },
  { key: 'taste', title: 'Taste', skippable: true, Component: TasteStub, isComplete: (s) => s.tasteSwipes.length > 0 },
  { key: 'occasions', title: 'Occasions', skippable: true, Component: OccasionsStub, isComplete: (s) => s.occasions.length > 0 },
  { key: 'weather', title: 'Weather', skippable: true, Component: WeatherStub, isComplete: (s) => !!s.location },
];
