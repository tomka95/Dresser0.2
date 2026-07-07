import React from 'react';

import { Splash } from '@/components/ds';

/** Root route-transition loading state — brand splash, no shell chrome. */
export default function Loading() {
  return (
    <div className="relative h-full min-h-full w-full" style={{ background: 'var(--app-bg)' }}>
      <Splash hint="Setting the fitting room…" />
    </div>
  );
}
