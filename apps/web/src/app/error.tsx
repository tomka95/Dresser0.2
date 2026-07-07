'use client';

import React from 'react';

import { CrashScreen } from '@/components/ds';
import { AppShell } from '@/components/layout/AppShell';

/**
 * Route-segment error boundary (§0 · G6). "Reload Tailor" retries the segment
 * via reset(); reporting has no endpoint yet so the button renders
 * disabled-honest inside CrashScreen.
 */
export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <AppShell scroll={false}>
      <div className="relative h-full">
        <CrashScreen onReload={reset} errorRef={error.digest} />
      </div>
    </AppShell>
  );
}
