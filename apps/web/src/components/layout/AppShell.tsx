import React from 'react';
import { cn } from '@/lib/utils';

interface AppShellProps {
  children: React.ReactNode;
  /** Extra classes for the scrolling content wrapper (e.g. padding). */
  contentClassName?: string;
  /** When false, the content area does not scroll (used by chat / review / 404). */
  scroll?: boolean;
  /** Dim the background further (used to give modals/sheets context). */
  dim?: boolean;
}

/**
 * Dark photographic app shell — frosted closet background + scrim gradient, over the
 * solid --app-bg fallback. The scrim (--grad-scrim) darkens the photo so content stays
 * legible; without it the backdrop washes out the UI. Card surfaces are opaque now (see
 * ItemImage), so the backdrop can't bleed through card image boxes. The layers are
 * pinned to the centered 430px column so they stay put while content scrolls above.
 */
export function AppShell({ children, contentClassName, scroll = true, dim = false }: AppShellProps) {
  return (
    <div className="relative min-h-full w-full" style={{ background: 'var(--app-bg)' }}>
      {/* Background image (over the --app-bg fallback). */}
      <div
        className="fixed top-0 bottom-0 left-1/2 -translate-x-1/2 w-full max-w-[430px] z-0"
        style={{
          background: 'var(--app-bg)',
          backgroundImage: "url('/images/closet-background-blur.jpg')",
          backgroundSize: 'cover',
          backgroundPosition: 'center',
        }}
        aria-hidden
      />
      {/* Scrim gradient — darkens the photo for legibility (the missing layer that made
          the backdrop look washed-out). */}
      <div
        className="fixed top-0 bottom-0 left-1/2 -translate-x-1/2 w-full max-w-[430px] z-0"
        style={{ background: 'var(--grad-scrim)' }}
        aria-hidden
      />
      {dim && (
        <div
          className="fixed top-0 bottom-0 left-1/2 -translate-x-1/2 w-full max-w-[430px] z-0"
          style={{ background: 'rgba(0,0,0,0.55)' }}
          aria-hidden
        />
      )}
      {/* Content */}
      <div className={cn('relative z-10', scroll ? '' : 'h-full overflow-hidden', contentClassName)}>
        {children}
      </div>
    </div>
  );
}
