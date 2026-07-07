'use client';

import React from 'react';

import { Sk } from '@/components/ds';

/**
 * OnboardingSkeleton — the O10 gated interstitial (§2 · O10).
 *
 * Rendered while the onboarding page's auth gate is still resolving (the hook's
 * `loading` state), in place of the old blank `null`. It mirrors the onboarding
 * chrome — a back-button placeholder, six progress dots (the first widened), a
 * title/subtitle pair, three option-card rows, and a pinned CTA bar — so the first
 * paint is the shape of the flow, never an empty screen. Fail-closed behavior is
 * unchanged: this only shows during `loading`; an unauthenticated user is still
 * redirected by the gate, and nothing here renders profile data.
 */
export function OnboardingSkeleton() {
  return (
    <div
      className="relative h-full min-h-full w-full overflow-hidden"
      style={{ background: 'var(--app-bg)' }}
      aria-busy
      aria-label="Loading onboarding"
    >
      {/* Backdrop photo + scrim, matching the live flow's Backdrop. */}
      <div
        className="pointer-events-none absolute inset-0 z-0"
        style={{
          backgroundImage: "url('/auth/closet-bg.jpg')",
          backgroundSize: 'cover',
          backgroundPosition: 'center',
          opacity: 0.4,
        }}
        aria-hidden
      />
      <div
        className="pointer-events-none absolute inset-0 z-0"
        style={{ background: 'var(--grad-scrim)' }}
        aria-hidden
      />

      <div className="absolute inset-0 z-10" style={{ padding: '64px 22px' }}>
        {/* Chrome — back · dots · skip */}
        <div className="flex items-center justify-between">
          <Sk w={38} h={38} r={13} />
          <div className="flex items-center gap-[7px]">
            {[0, 1, 2, 3, 4, 5].map((i) => (
              <Sk key={i} w={i === 0 ? 22 : 7} h={7} r={4} />
            ))}
          </div>
          <Sk w={30} h={14} r={7} />
        </div>

        {/* Title + subtitle */}
        <Sk w="72%" h={26} r={9} style={{ marginTop: 30 }} />
        <Sk w="52%" h={13} r={7} style={{ marginTop: 12 }} />

        {/* Option-card rows */}
        <div className="mt-[26px] flex flex-col gap-[11px]">
          <Sk h={76} r={22} />
          <Sk h={76} r={22} />
          <Sk h={76} r={22} />
        </div>

        {/* Pinned CTA */}
        <div className="absolute" style={{ left: 22, right: 22, bottom: 30 }}>
          <Sk h={52} r={999} mint />
        </div>
      </div>
    </div>
  );
}
