'use client';

import React from 'react';

import { M } from '@/components/ds';

/**
 * OnboardingStep — the shared frame every onboarding screen renders inside
 * (§2 · Onb). A big serif-weight title, an optional subtitle, and the question
 * body. Navigation chrome (progress dots, back/skip/continue, background photo)
 * lives in OnboardingFlow, NOT here — screens only own their question. Keep one
 * question per screen (≤90s total).
 */
export function OnboardingStep({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle?: string;
  children?: React.ReactNode;
}) {
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <h1
        className="m-0 text-[27px] font-bold leading-[1.15]"
        style={{ color: '#fff', letterSpacing: '-0.7px' }}
      >
        {title}
      </h1>
      {subtitle ? (
        <p
          className="m-0 mt-2 max-w-[300px] text-[14.5px] leading-relaxed"
          style={{ color: M.faint }}
        >
          {subtitle}
        </p>
      ) : null}
      {/* min-h-0 so a screen body's own overflow-y-auto region scrolls instead of
          pushing the fixed footer (sizes / weather can exceed the viewport). */}
      <div className="mt-6 flex min-h-0 flex-1 flex-col">{children}</div>
    </div>
  );
}
