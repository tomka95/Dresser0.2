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
// Fallback when the image's own background can't be sampled (CORS-tainted canvas, load
// error). A soft off-white blends with the pale product-card backgrounds we generate.
const FALLBACK_OFFWHITE = '#f2f1ee';

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
  /**
   * Sample the image's own background color (its top-left corner pixel) and use it as
   * the panel backing, so a `contain` image blends seamlessly with no letterbox bars.
   * Used by the generated product cards, whose whites vary (warm/cool/pure). Falls back
   * to a neutral off-white when the pixel can't be read (CORS / load error).
   */
  sampleBackground?: boolean;
}

export function ItemImage({
  src,
  alt,
  fit = 'cover',
  emptyLabel = 'No image',
  className,
  imgClassName,
  sampleBackground = false,
}: ItemImageProps) {
  const [loaded, setLoaded] = useState(false);
  const [errored, setErrored] = useState(false);
  // The color sampled from THIS src's corner (null until read / on failure).
  const [sampledBg, setSampledBg] = useState<string | null>(null);

  // The deck reuses this instance across cards (src prop changes) — reset load/error
  // state whenever the src changes so a prior error can't suppress a new valid image.
  useEffect(() => {
    setLoaded(false);
    setErrored(false);
  }, [src]);

  // Sample the image's background from its top-left pixel via a SEPARATE crossOrigin
  // probe image (never the visible <img>, which has no crossOrigin and always loads).
  // If the host lacks CORS headers the probe errors, or the canvas is tainted and
  // getImageData throws — either way we fall back to a neutral off-white. The visible
  // image is unaffected by any of this.
  useEffect(() => {
    setSampledBg(null);
    if (!sampleBackground || !src || typeof window === 'undefined') return;
    let cancelled = false;
    const probe = new window.Image();
    probe.crossOrigin = 'anonymous';
    probe.onload = () => {
      if (cancelled) return;
      try {
        const canvas = document.createElement('canvas');
        canvas.width = 1;
        canvas.height = 1;
        const ctx = canvas.getContext('2d');
        if (!ctx) return;
        // Draw only the top-left source pixel into the 1×1 canvas, then read it back.
        ctx.drawImage(probe, 0, 0, 1, 1, 0, 0, 1, 1);
        const [r, g, b] = ctx.getImageData(0, 0, 1, 1).data;
        if (!cancelled) setSampledBg(`rgb(${r}, ${g}, ${b})`);
      } catch {
        /* tainted canvas / read blocked → keep the off-white fallback */
      }
    };
    probe.onerror = () => {
      /* CORS/load failure → keep the off-white fallback */
    };
    probe.src = src;
    return () => {
      cancelled = true;
    };
  }, [src, sampleBackground]);

  // In sampling mode the backing is the image's own bg (sampled, else off-white) so a
  // `contain` image shows no bars; otherwise the opaque neutral panel.
  const background = sampleBackground ? sampledBg ?? FALLBACK_OFFWHITE : NEUTRAL_BG;

  return (
    <div
      className={cn('relative h-full w-full overflow-hidden', className)}
      style={{ background }}
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
