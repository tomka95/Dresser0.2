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
 * Dark photographic app shell — frosted closet background over the solid --app-bg
 * fallback. The card surfaces are opaque now (see ItemImage), so this z-0 backdrop can
 * no longer bleed through card image boxes; it is purely decorative. --app-bg stays as
 * the color behind/fallback. The layer is pinned to the centered 430px column so it
 * stays put while content scrolls above it.
 */
export function AppShell({ children, contentClassName, scroll = true, dim = false }: AppShellProps) {
  return (
    <div className="relative min-h-full w-full" style={{ background: 'var(--app-bg)' }}>
      {/* Decorative closet backdrop (over the --app-bg fallback). */}
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
