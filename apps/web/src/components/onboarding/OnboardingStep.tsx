'use client';

import React from 'react';

/**
 * OnboardingStep — the shared frame every onboarding screen renders inside.
 *
 * A screen branch replaces a step stub (see ./steps/) with real content but keeps
 * this frame: a title, an optional subtitle, and the question body. Navigation
 * chrome (progress dots, back/skip/continue) lives in OnboardingFlow, NOT here —
 * screens only own their question. Keep one question per screen (≤90s total).
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
    <div className="flex min-h-0 flex-1 flex-col px-1 pt-2">
      <h1 className="m-0 mb-2 text-[26px] font-bold leading-tight tracking-[-0.4px] text-white">
        {title}
      </h1>
      {subtitle ? (
        <p className="m-0 mb-6 max-w-[320px] text-[15px] leading-relaxed text-white/65">
          {subtitle}
        </p>
      ) : (
        <div className="mb-6" />
      )}
      {/* min-h-0 so a screen body's own overflow-y-auto region scrolls instead of
          pushing the fixed footer (sizes / weather can exceed the viewport). */}
      <div className="flex min-h-0 flex-1 flex-col">{children}</div>
    </div>
  );
}
