'use client';

/**
 * /outfits — outfit suggestion cards (design restyle).
 * Data is the MOCK suggestions store (no outfits backend yet); likes are
 * client-side only. Closet thumbnails are REAL item images.
 */

import { useEffect, useMemo } from 'react';
import { useRouter } from 'next/navigation';
import { Heart, RotateCw } from 'lucide-react';

import { track } from '@/lib/analytics';
import { useClosetStore } from '@/stores/useClosetStore';
import { useOutfitsStore } from '@/stores/useOutfitsStore';
import { AppShell } from '@/components/layout/AppShell';
import { ItemImage } from '@/components/ui/ItemImage';
import { DSButton, GlassCard, Spark } from '@/components/ds';

export default function OutfitsPage() {
  const router = useRouter();
  const outfits = useOutfitsStore((state) => state.outfits);
  const likedOutfits = useOutfitsStore((state) => state.likedOutfits);
  const isLoading = useOutfitsStore((state) => state.isLoading);
  const error = useOutfitsStore((state) => state.error);
  const fetchOutfits = useOutfitsStore((state) => state.fetchOutfits);
  const toggleLike = useOutfitsStore((state) => state.toggleLike);

  const closetItems = useClosetStore((state) => state.items);
  const closetLoading = useClosetStore((state) => state.isLoading);
  const fetchClosetItems = useClosetStore((state) => state.fetchItems);

  useEffect(() => {
    // Track page view when component mounts
    track('outfit_suggestions_viewed', {
      outfit_count: outfits.length,
      has_recommended_items: outfits.some(
        (o) => o.recommendedItems && o.recommendedItems.length > 0
      ),
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (outfits.length === 0 && !isLoading) {
      fetchOutfits({ limit: 3 });
    }
  }, [fetchOutfits, isLoading, outfits.length]);

  useEffect(() => {
    if (closetItems.length === 0 && !closetLoading) {
      fetchClosetItems();
    }
  }, [closetItems.length, closetLoading, fetchClosetItems]);

  // Track successful outfit suggestions load
  useEffect(() => {
    if (outfits.length > 0 && !isLoading) {
      track('outfit_suggestions_loaded', {
        count: outfits.length,
        has_recommended_items: outfits.some(
          (o) => o.recommendedItems && o.recommendedItems.length > 0
        ),
        total_recommended_items: outfits.reduce(
          (sum, o) => sum + (o.recommendedItems?.length || 0),
          0
        ),
      });
    }
  }, [outfits, isLoading]);

  const closetMap = useMemo(
    () => new Map(closetItems.map((item) => [item.id, item])),
    [closetItems]
  );

  async function handleRegenerate() {
    track('outfit_regenerate_clicked');
    try {
      await fetchOutfits({ limit: 3 });
    } catch (error) {
      track('outfit_regenerate_failed', {
        error: error instanceof Error ? error.message : 'Unknown error',
      });
    }
  }

  const showEmpty = outfits.length === 0 && !isLoading;

  return (
    <AppShell>
      <div style={{ padding: '52px 24px 120px' }}>
        <div className="mb-[18px] flex items-center justify-between">
          <h1 className="m-0 text-[32px] font-bold tracking-[-0.5px] text-white">Outfits</h1>
          <button
            type="button"
            onClick={handleRegenerate}
            disabled={isLoading}
            className="flex items-center gap-[7px] rounded-full text-[13px] font-semibold text-white disabled:opacity-50"
            style={{ padding: '9px 14px', border: '1px solid var(--tr-20)', background: 'var(--tr-10)' }}
          >
            <RotateCw size={15} className={isLoading ? 'animate-spin' : undefined} /> Regenerate
          </button>
        </div>

        {isLoading && (
          <div className="py-3 text-sm text-white/60">Generating personalized looks…</div>
        )}
        {error && (
          <div className="py-3 text-sm" style={{ color: 'var(--danger)' }}>
            {error}. Please try again.
          </div>
        )}

        {showEmpty ? (
          <div className="flex flex-col items-center px-4 pt-20 text-center">
            <div
              className="mb-[22px] flex items-center justify-center rounded-full"
              style={{ width: 96, height: 96, background: 'var(--tr-10)', border: '1px solid var(--tr-20)' }}
            >
              <span style={{ fontSize: 38, color: 'var(--mint)' }}>✦</span>
            </div>
            <h2 className="m-0 mb-2.5 text-[22px] font-bold tracking-[-0.3px] text-white">No outfits yet</h2>
            <p className="mx-auto mb-6 max-w-[280px] text-[14.5px] leading-relaxed text-white/[0.65]">
              Add a few more items and Tailor will generate outfits tailored to your week.
            </p>
            <DSButton
              variant="light"
              pill
              leftIcon={<RotateCw size={17} />}
              style={{ height: 48, padding: '0 26px' }}
              onClick={handleRegenerate}
            >
              Generate outfits
            </DSButton>
          </div>
        ) : (
          <div className="flex flex-col gap-4">
            {outfits.map((outfit) => {
              const isLiked = likedOutfits.includes(outfit.id);
              const itemsWithData = outfit.items
                .map((itemId) => closetMap.get(itemId))
                .filter((i): i is NonNullable<typeof i> => !!i);

              return (
                <GlassCard
                  key={outfit.id}
                  tint="frost"
                  padding={16}
                  className="cursor-pointer"
                  role="button"
                  onClick={() => router.push(`/outfits/${outfit.id}`)}
                >
                  <div className="mb-3 flex items-center justify-between">
                    <div>
                      <div className="text-[18px] font-bold text-white">{outfit.name ?? 'Outfit'}</div>
                      {outfit.occasion && <div className="text-[13px] text-white/60">{outfit.occasion}</div>}
                    </div>
                    <button
                      type="button"
                      aria-label={isLiked ? 'Unlike outfit' : 'Like outfit'}
                      onClick={(e) => {
                        e.stopPropagation();
                        const wasLiked = isLiked;
                        toggleLike(outfit.id);
                        track(wasLiked ? 'outfit_unliked' : 'outfit_liked', {
                          outfit_id: outfit.id,
                          has_recommended_items: (outfit.recommendedItems?.length || 0) > 0,
                          occasion: outfit.occasion,
                        });
                      }}
                      className="flex items-center justify-center rounded-full transition-transform active:scale-90"
                      style={{
                        width: 38,
                        height: 38,
                        border: '1px solid var(--tr-20)',
                        background: 'rgba(0,0,0,0.25)',
                        color: isLiked ? 'var(--mint)' : 'rgba(255,255,255,0.85)',
                      }}
                    >
                      <Heart size={18} fill={isLiked ? 'currentColor' : 'none'} />
                    </button>
                  </div>

                  {itemsWithData.length > 0 ? (
                    <div className="flex gap-2">
                      {itemsWithData.map((item) => (
                        <div
                          key={item.id}
                          className="flex-1 overflow-hidden rounded-[10px]"
                          style={{ aspectRatio: '3/4', border: '1px solid rgba(255,255,255,0.1)' }}
                        >
                          <ItemImage src={item.imageUrl} alt={item.name} fit="cover" />
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p className="m-0 text-[13px] text-white/50">
                      This look&rsquo;s items aren&rsquo;t in your closet yet.
                    </p>
                  )}

                  {outfit.recommendedItems && outfit.recommendedItems.length > 0 && (
                    <div
                      className="mt-3 flex items-center gap-2 rounded-xl"
                      style={{ padding: '10px 12px', background: 'var(--grad-ai)', border: '1px solid var(--tr-20)' }}
                    >
                      <span style={{ color: 'var(--mint)' }}>✦</span>
                      <span className="text-[13px] text-white">
                        Add {outfit.recommendedItems[0].name.toLowerCase()} to finish this look
                      </span>
                    </div>
                  )}
                </GlassCard>
              );
            })}
          </div>
        )}
      </div>
    </AppShell>
  );
}
