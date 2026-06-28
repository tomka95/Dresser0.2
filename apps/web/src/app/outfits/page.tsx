'use client';

// TODO: outfits are mock — useOutfitsStore has no backend; like state is local

import { useEffect, useMemo } from 'react';
import { Heart, RotateCw } from 'lucide-react';

import { useRequireAuth } from '@/lib/auth/useRequireAuth';
import { useClosetStore } from '@/stores/useClosetStore';
import { useOutfitsStore } from '@/stores/useOutfitsStore';
import { AppShell } from '@/components/layout/AppShell';
import { GlassCard } from '@/components/ui/GlassCard';
import { EmptyState } from '@/components/ui/EmptyState';

const FALLBACK_IMG =
  'data:image/svg+xml;utf8,' +
  encodeURIComponent(
    "<svg xmlns='http://www.w3.org/2000/svg' width='300' height='400'><rect width='100%' height='100%' fill='%23333'/></svg>"
  );

export default function OutfitsPage() {
  const { status } = useRequireAuth();
  const isAuth = status === 'authenticated';

  const outfits = useOutfitsStore((s) => s.outfits);
  const likedOutfits = useOutfitsStore((s) => s.likedOutfits);
  const isLoading = useOutfitsStore((s) => s.isLoading);
  const error = useOutfitsStore((s) => s.error);
  const fetchOutfits = useOutfitsStore((s) => s.fetchOutfits);
  const toggleLike = useOutfitsStore((s) => s.toggleLike);

  const closetItems = useClosetStore((s) => s.items);
  const fetchItems = useClosetStore((s) => s.fetchItems);

  useEffect(() => {
    if (!isAuth) return;
    fetchOutfits();
    fetchItems();
  }, [isAuth, fetchOutfits, fetchItems]);

  const closetMap = useMemo(
    () => new Map(closetItems.map((item) => [item.id, item])),
    [closetItems]
  );

  if (status === 'loading' || !isAuth) {
    return (
      <AppShell contentClassName="px-6 pt-14">
        <div className="h-9 w-40 rounded-xl bg-white/5 animate-pulse" />
      </AppShell>
    );
  }

  const isEmpty = outfits.length === 0 && !isLoading;

  return (
    <AppShell contentClassName="px-6 pt-14 pb-12">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <h1 className="m-0 text-[32px] font-bold leading-none text-white" style={{ letterSpacing: '-0.5px' }}>
          Outfits
        </h1>
        <button
          type="button"
          onClick={() => fetchOutfits()}
          disabled={isLoading}
          className="inline-flex items-center gap-2 rounded-full px-4 py-2 text-[14px] font-medium text-white transition-transform active:scale-[0.97] disabled:opacity-60"
          style={{ background: 'var(--tr-10)', border: '1px solid var(--tr-20)' }}
        >
          <RotateCw size={16} className={isLoading ? 'animate-spin' : undefined} />
          Regenerate
        </button>
      </div>

      {error && (
        <p className="mb-4 text-[14px]" style={{ color: 'var(--danger)' }}>
          {error}
        </p>
      )}

      {isLoading && outfits.length === 0 && (
        <div className="space-y-4">
          {[0, 1].map((i) => (
            <div key={i} className="h-56 rounded-[24px] bg-white/5 animate-pulse" />
          ))}
        </div>
      )}

      {isEmpty && !error && (
        <div className="pt-24">
          <EmptyState
            icon={<span style={{ fontSize: 38, color: 'var(--mint)' }}>✦</span>}
            title="No outfits yet"
            body="Add a few more items and Tailor will generate outfits tailored to your week."
            ctaLabel="Generate outfits"
            ctaIcon={<RotateCw size={18} />}
            onCta={() => fetchOutfits()}
          />
        </div>
      )}

      {!isEmpty && (
        <div className="space-y-4">
          {outfits.map((outfit, idx) => {
            const liked = likedOutfits.includes(outfit.id);
            const resolved = outfit.items
              .map((itemId) => closetMap.get(itemId))
              .filter((item): item is NonNullable<typeof item> => Boolean(item));

            return (
              <GlassCard key={outfit.id} tint="frost" padding={16}>
                {/* Card header */}
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <h2 className="m-0 truncate text-[18px] font-bold text-white">
                      {outfit.name || `Look ${idx + 1}`}
                    </h2>
                    {outfit.occasion && (
                      <p className="m-0 mt-0.5 text-[13px] capitalize" style={{ color: 'rgba(255,255,255,0.6)' }}>
                        {outfit.occasion}
                      </p>
                    )}
                  </div>
                  <button
                    type="button"
                    onClick={() => toggleLike(outfit.id)}
                    aria-label={liked ? 'Unlike outfit' : 'Like outfit'}
                    className="flex items-center justify-center transition-transform active:scale-90"
                    style={{
                      width: 38,
                      height: 38,
                      borderRadius: '50%',
                      flexShrink: 0,
                      background: 'rgba(0,0,0,0.28)',
                      border: '1px solid var(--tr-20)',
                      color: liked ? 'var(--mint)' : 'rgba(255,255,255,0.85)',
                    }}
                  >
                    <Heart size={18} fill={liked ? 'currentColor' : 'none'} />
                  </button>
                </div>

                {/* Item thumbnails */}
                <div className="mt-3.5">
                  {resolved.length > 0 ? (
                    <div className="flex gap-2">
                      {resolved.map((item) => (
                        <div
                          key={item.id}
                          className="flex-1 aspect-[3/4] overflow-hidden rounded-2xl"
                          style={{ background: 'rgba(255,255,255,0.06)' }}
                        >
                          {/* eslint-disable-next-line @next/next/no-img-element */}
                          <img
                            src={item.imageUrl || FALLBACK_IMG}
                            alt={item.name}
                            loading="lazy"
                            className="h-full w-full object-cover"
                          />
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p className="m-0 text-[13px]" style={{ color: 'rgba(255,255,255,0.5)' }}>
                      Items unavailable
                    </p>
                  )}
                </div>

                {/* AI recommended addition strip — first card only */}
                {idx === 0 && (
                  <div
                    className="mt-3.5 flex items-center gap-2.5 rounded-2xl px-3.5 py-3"
                    style={{ background: 'var(--grad-ai)', border: '1px solid var(--tr-20)' }}
                  >
                    <span style={{ color: 'var(--mint)', fontSize: 16, flexShrink: 0 }}>✦</span>
                    <span className="text-[13.5px] text-white">Add a scarf to finish this look</span>
                  </div>
                )}
              </GlassCard>
            );
          })}
        </div>
      )}
    </AppShell>
  );
}
