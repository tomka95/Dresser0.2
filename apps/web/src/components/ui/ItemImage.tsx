'use client';

import { useEffect, useState } from 'react';
import { cn } from '@/lib/utils';

/**
 * ItemImage — the ONE shared render path for a clothing image (closet grid, home,
 * item detail, review deck).
 *
 * Structure: an OPAQUE neutral panel (parent). Exactly one child renders at a time:
 *   - a loaded/valid image  -> the <img> (absolute-fills the panel), OR
 *   - the "No image" placeholder -> only when there is NO src or the <img> errored.
 * They never coexist, so a successfully-loaded image can never be covered by the
 * placeholder (the bug this fixes). The <img> is absolutely positioned filling the
 * panel (inset-0, 100%/100%, block), so it can't collapse on a broken height chain —
 * callers still give the wrapping box a resolved height (aspect-ratio / min-height).
 *
 * plain <img src> — no next/image, no fetch, no blob/object-URL. On error the <img>
 * UNMOUNTS (not an opacity/visibility gate that could stick hidden) and the placeholder
 * takes its place.
 */

// Opaque neutral backing (a hair above --app-bg #1e1e1e). MUST be opaque so nothing
// behind the card image (e.g. the app backdrop) can bleed through.
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
  const [loaded, setLoaded] = useState(false);
  const [errored, setErrored] = useState(false);

  // The deck reuses this instance across cards (src prop changes) — reset load/error
  // state whenever the src changes so a prior error can't suppress a new valid image.
  useEffect(() => {
    setLoaded(false);
    setErrored(false);
  }, [src]);

  return (
    <div
      className={cn('relative h-full w-full overflow-hidden', className)}
      style={{ background: NEUTRAL_BG }}
      data-loaded={loaded}
    >
      {/* Placeholder ONLY when there's no usable image — never while a valid one loads. */}
      {(!src || errored) && (
        <div className="absolute inset-0 flex items-center justify-center px-2 text-center">
          <span className="text-[12px]" style={{ color: 'rgba(255,255,255,0.35)' }}>
            {emptyLabel}
          </span>
        </div>
      )}

      {/* Valid src: the <img> absolute-fills the panel and covers it once painted. On
          error it unmounts (no opacity gate) and the placeholder above renders instead. */}
      {src && !errored ? (
        /* eslint-disable-next-line @next/next/no-img-element */
        <img
          src={src}
          alt={alt}
          className={cn(
            'absolute inset-0 block h-full w-full',
            fit === 'contain' ? 'object-contain' : 'object-cover',
            imgClassName,
          )}
          onLoad={() => setLoaded(true)}
          onError={() => setErrored(true)}
        />
      ) : null}
    </div>
  );
}
