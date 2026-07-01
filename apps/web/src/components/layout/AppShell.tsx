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
 * Dark app shell with a SOLID neutral background — not a photo.
 *
 * A decorative fixed z-0 closet stock image (`/images/closet-background-blur.jpg`) used
 * to live here. A photo backdrop masquerades as broken/loaded images: any transparent
 * card box, decode gap, or empty/loading/error state shows it straight through and
 * reads as a "dark luxury closet" placeholder — masking real rendering bugs. Replaced
 * with the solid --app-bg token so those states read as plainly empty. The layer is
 * pinned to the centered 430px column so it stays put while content scrolls above it.
 */
export function AppShell({ children, contentClassName, scroll = true, dim = false }: AppShellProps) {
  return (
    <div className="relative min-h-full w-full" style={{ background: 'var(--app-bg)' }}>
      {/* Solid neutral backdrop (no stock photo). */}
      <div
        className="fixed top-0 bottom-0 left-1/2 -translate-x-1/2 w-full max-w-[430px] z-0"
        style={{ background: 'var(--app-bg)' }}
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
