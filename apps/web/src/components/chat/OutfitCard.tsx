'use client';

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
 */
export function OutfitCard({ outfit }: { outfit: ChatOutfitPayload }) {
  return (
    <>
      {outfit.collageUrl && (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={outfit.collageUrl}
          alt="Outfit collage"
          className="mt-2 rounded-[14px]"
          style={{
            width: '100%',
            maxWidth: 300,
            border: '1px solid var(--tr-20)',
            background: 'rgb(242, 242, 242)',
          }}
        />
      )}
      <OutfitStrip outfit={outfit} />
    </>
  );
}
