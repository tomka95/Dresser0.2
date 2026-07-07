'use client';

import { useState } from 'react';
import { ImageIcon } from 'lucide-react';
import type { ChatOutfitPayload } from '@tailor/contracts';

import { ItemImage } from '@/components/ui/ItemImage';

/** Per-item strip under an outfit — 3:4 thumbs; tappable in swap mode. */
export function OutfitStrip({
  outfit,
  onSlotTap,
  activeSlot,
}: {
  outfit: ChatOutfitPayload;
  onSlotTap?: (slot: string) => void;
  activeSlot?: string | null;
}) {
  const items = Object.entries(outfit.slots);
  if (items.length === 0) return null;
  return (
    <div className="mt-2 flex gap-2 overflow-x-auto scrollbar-hide">
      {items.map(([slot, item]) => {
        const tappable = !!onSlotTap;
        const active = activeSlot === slot;
        const inner = (
          <>
            <div
              className="overflow-hidden rounded-[10px]"
              style={{
                width: 72,
                aspectRatio: '3/4',
                border: active ? '2px solid var(--mint)' : '1px solid var(--tr-20)',
              }}
            >
              <ItemImage src={item.imageUrl ?? undefined} alt={item.name} fit="cover" />
            </div>
            <div
              className="mt-1 truncate text-center text-[10px]"
              style={{ color: active ? 'var(--mint)' : 'rgba(255,255,255,0.6)' }}
            >
              {tappable ? 'Swap' : item.name}
            </div>
          </>
        );
        return tappable ? (
          <button
            key={slot}
            type="button"
            onClick={() => onSlotTap?.(slot)}
            className="shrink-0 text-left"
            style={{ width: 72 }}
            aria-label={`Swap ${item.name}`}
          >
            {inner}
          </button>
        ) : (
          <div key={slot} className="shrink-0" style={{ width: 72 }}>
            {inner}
          </div>
        );
      })}
    </div>
  );
}

/**
 * The composed-outfit card inside a chat bubble: an optional server-tiled collage
 * image (from the user's own item photos) above the per-item OutfitStrip. Plain
 * <img> like ItemImage — remote Supabase URL, no next/image.
 *
 * States: while the collage <img> loads we hold a skeleton in its place (no
 * layout jump); if it fails outright we drop the image and fall back gracefully
 * to the item strip (which always renders from the user's own item photos).
 */
export function OutfitCard({ outfit }: { outfit: ChatOutfitPayload }) {
  // 'loading' until the collage paints; 'error' → fall back to the strip alone.
  const [collageState, setCollageState] = useState<'loading' | 'loaded' | 'error'>('loading');
  const showCollage = !!outfit.collageUrl && collageState !== 'error';

  return (
    <>
      {showCollage && (
        <div
          className="relative mt-2 overflow-hidden rounded-[14px]"
          style={{ width: '100%', maxWidth: 300, border: '1px solid var(--tr-20)', background: 'rgb(242, 242, 242)' }}
        >
          {collageState === 'loading' && (
            <div
              className="t2-sk absolute inset-0"
              style={{ aspectRatio: '4/3' }}
              aria-label="Loading outfit collage"
            />
          )}
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={outfit.collageUrl ?? undefined}
            alt="Outfit collage"
            className="block w-full"
            style={{ opacity: collageState === 'loaded' ? 1 : 0, transition: 'opacity 0.2s' }}
            onLoad={() => setCollageState('loaded')}
            onError={() => setCollageState('error')}
          />
        </div>
      )}
      {outfit.collageUrl && collageState === 'error' && (
        <div
          className="mt-2 inline-flex items-center gap-1.5 text-[11px]"
          style={{ color: 'rgba(255,255,255,0.5)' }}
          role="status"
        >
          <ImageIcon size={12} /> Collage didn&rsquo;t render — showing the pieces
        </div>
      )}
      <OutfitStrip outfit={outfit} />
    </>
  );
}
