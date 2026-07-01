'use client';

import { cn } from '@/lib/utils';

/**
 * ItemImage — the ONE shared render path for a clothing image (closet grid, home,
 * item detail, review deck).
 *
 * Why this exists: each screen used its own ad-hoc <img>, and the broken ones sat on a
 * TRANSPARENT box. When the image didn't paint (decode gap, blend mode, empty url) the
 * app's fixed z-0 backdrop (`/images/closet-background-blur.jpg`) showed straight
 * through — reading as a misleading dark "closet" stock photo. This component fixes
 * that at the source:
 *   - always renders on an OPAQUE neutral panel, so the backdrop can never bleed through
 *   - plain <img> (no next/image config to miss) with a real object-fit box
 *   - NO mix-blend (which was silently erasing neutral-background cutouts on /home)
 *   - onError hides the broken <img>, revealing the neutral empty state beneath —
 *     never a stock photo
 *
 * Client component: the onError handler is a client-only feature (all current callers
 * already sit inside 'use client' boundaries). No React state — cheap to render.
 */

// Opaque neutral backing (a hair above --app-bg #1e1e1e). MUST be opaque so the fixed
// AppShell backdrop is never visible behind a card image.
const NEUTRAL_BG = '#242424';

interface ItemImageProps {
  src?: string | null;
  alt: string;
  /** 'cover' fills the box (grid/deck cards); 'contain' shows the whole garment. */
  fit?: 'cover' | 'contain';
  /** Text for the neutral empty/error state. */
  emptyLabel?: string;
  /** Classes for the outer box (sizing/rounding come from the caller's layout). */
  className?: string;
  /** Extra classes for the <img> (e.g. hover scale on closet cards). */
  imgClassName?: string;
}

export function ItemImage({
  src,
  alt,
  fit = 'cover',
  emptyLabel = 'No image',
  className,
  imgClassName,
}: ItemImageProps) {
  return (
    <div
      className={cn('relative h-full w-full overflow-hidden', className)}
      style={{ background: NEUTRAL_BG }}
    >
      {/* Neutral empty state sits BEHIND the image: shown when there's no src, or when
          the <img> fails to load (onError hides the img and this shows through). */}
      <div className="absolute inset-0 flex items-center justify-center px-2 text-center">
        <span className="text-[12px]" style={{ color: 'rgba(255,255,255,0.35)' }}>
          {emptyLabel}
        </span>
      </div>

      {src ? (
        /* eslint-disable-next-line @next/next/no-img-element */
        <img
          src={src}
          alt={alt}
          className={cn(
            'relative h-full w-full',
            fit === 'contain' ? 'object-contain' : 'object-cover',
            imgClassName,
          )}
          onError={(e) => {
            // Reveal the neutral panel beneath instead of a broken-image glyph or the
            // app backdrop. Clear the handler first so it can't loop.
            e.currentTarget.onerror = null;
            e.currentTarget.style.visibility = 'hidden';
          }}
        />
      ) : null}
    </div>
  );
}
