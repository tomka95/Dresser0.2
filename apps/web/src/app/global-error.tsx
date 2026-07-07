'use client';

import React from 'react';

import { CrashScreen } from '@/components/ds';

/**
 * Root error boundary — replaces the entire root layout, so it must render its
 * own <html>/<body> and cannot assume globals.css loaded. The needed design
 * tokens are re-declared inline on the wrapper.
 */
export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <html lang="en">
      <body style={{ margin: 0, background: '#101615' }}>
        <div
          className="relative"
          style={
            {
              position: 'relative',
              minHeight: '100vh',
              maxWidth: 430,
              margin: '0 auto',
              background: '#101615',
              fontFamily:
                "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif",
              // globals.css may not be loaded here — re-declare the tokens CrashScreen uses.
              '--mint': '#4be2d6',
              '--ease-out': 'cubic-bezier(0.22, 1, 0.36, 1)',
              '--spring': 'cubic-bezier(0.34, 1.56, 0.64, 1)',
            } as React.CSSProperties
          }
        >
          <CrashScreen onReload={reset} errorRef={error.digest} />
        </div>
      </body>
    </html>
  );
}
