'use client';

import React from 'react';

import { OfflineBanner } from '@/components/ds/StateBlock';
import { useOnline } from '@/lib/useOnline';

/**
 * §0 · G7 — Global offline pill. Mounted once in AppShell; floats centered
 * near the top of the 430px column whenever the device loses connectivity.
 */
export function OfflineIndicator() {
  const online = useOnline();
  if (online) return null;
  return (
    <div className="pointer-events-none fixed left-0 right-0 top-3 z-[45] mx-auto w-full max-w-[430px]">
      <OfflineBanner />
    </div>
  );
}
