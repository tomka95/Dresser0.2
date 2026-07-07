'use client';

/**
 * /outfits — Lookbook (design restyle).
 *
 * Data is the MOCK suggestions store (no outfits backend yet); likes are
 * client-side only ("Saved on this device"). Closet thumbnails are REAL item
 * images. Auth-guarded to match /outfits/[id].
 */

import { useEffect, useMemo } from 'react';
import { useRouter } from 'next/navigation';

import { track } from '@/lib/analytics';
import { useRequireAuth } from '@/lib/auth/useRequireAuth';
import { useClosetStore } from '@/stores/useClosetStore';
import { useOutfitsStore } from '@/stores/useOutfitsStore';
import { AppShell } from '@/components/layout/AppShell';
import { BottomNavBar } from '@/components/layout/BottomNavBar';
import { ItemImage } from '@/components/ui/ItemImage';
import {
  Btn,
  ErrorState,
  Icon,
  M,
  NAV_CLEAR,
  RoundBtn,
  SkList,
  StateBlock,
  StylistMark,
} from '@/components/ds';

export default function OutfitsPage() {
  const router = useRouter();

  // Auth guard — parity with /outfits/[id] (the list had none before).
  const { session, loading } = useRequireAuth();
  const isAuth = !!session;

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
    if (!isAuth) return;
    track('outfit_suggestions_viewed', {
      outfit_count: outfits.length,
      has_recommended_items: outfits.some(
        (o) => o.recommendedItems && o.recommendedItems.length > 0
      ),
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isAuth]);

  useEffect(() => {
    if (!isAuth) return;
    if (outfits.length === 0 && !isLoading) fetchOutfits({ limit: 3 });
  }, [isAuth, fetchOutfits, isLoading, outfits.length]);

  useEffect(() => {
    if (!isAuth) return;
    if (closetItems.length === 0 && !closetLoading) fetchClosetItems();
  }, [isAuth, closetItems.length, closetLoading, fetchClosetItems]);

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
    } catch (err) {
      track('outfit_regenerate_failed', {
        error: err instanceof Error ? err.message : 'Unknown error',
      });
    }
  }

  if (loading || !isAuth) return null;

  const showEmpty = outfits.length === 0 && !isLoading && !error;

  return (
    <AppShell>
      <div style={{ padding: '70px 20px', paddingBottom: NAV_CLEAR + 14 }}>
        {/* Header */}
        <div className="flex items-end justify-between">
          <div>
            <h1 className="m-0 text-[30px] font-bold text-white" style={{ letterSpacing: '-0.8px' }}>
              Lookbook
            </h1>
            <div className="mt-[3px] text-[13.5px]" style={{ color: M.faint }}>
              Outfits Tailor built from your closet
            </div>
          </div>
          <Btn
            variant="glass"
            size="sm"
            icon={<StylistMark size={13} />}
            onClick={handleRegenerate}
            pending={isLoading}
          >
            New look
          </Btn>
        </div>

        {/* Loading */}
        {isLoading && outfits.length === 0 && (
          <div className="mt-4">
            <SkList n={3} />
          </div>
        )}

        {/* Error */}
        {error && outfits.length === 0 && (
          <div className="mt-6">
            <ErrorState
              compact
              title="Couldn’t load your looks"
              sub={`${error}. Your closet is safe.`}
              onRetry={handleRegenerate}
            />
          </div>
        )}

        {/* Empty */}
        {showEmpty && (
          <div className="mt-6">
            <StateBlock
              tone="mint"
              icon={<StylistMark size={26} />}
              title="No outfits yet"
              sub="Ask the stylist for a look, or let Tailor propose one from today's weather."
              cta={
                <Btn variant="mint" size="md" icon={<StylistMark size={13} />} onClick={handleRegenerate}>
                  Style me for today
                </Btn>
              }
              cta2={
                <Btn variant="ghost" size="md" onClick={() => router.push('/chat')}>
                  Open chat
                </Btn>
              }
            />
          </div>
        )}

        {/* Populated */}
        {!showEmpty && !error && outfits.length > 0 && (
          <div className="mt-3 flex flex-col gap-3">
            {outfits.map((outfit) => {
              const isLiked = likedOutfits.includes(outfit.id);
              const itemsWithData = outfit.items
                .map((itemId) => closetMap.get(itemId))
                .filter((i): i is NonNullable<typeof i> => !!i);

              return (
                <div
                  key={outfit.id}
                  role="button"
                  tabIndex={0}
                  onClick={() => router.push(`/outfits/${outfit.id}`)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') router.push(`/outfits/${outfit.id}`);
                  }}
                  className="flex cursor-pointer items-center gap-3.5"
                  style={{ ...M.glass(24), padding: 14 }}
                >
                  {/* 2×2 thumb grid */}
                  <div
                    className="shrink-0"
                    style={{
                      display: 'grid',
                      gridTemplateColumns: '46px 46px',
                      gridTemplateRows: '56px 56px',
                      gap: 3,
                    }}
                  >
                    {itemsWithData.slice(0, 4).map((it, j) => (
                      <div
                        key={it.id}
                        className="overflow-hidden"
                        style={{
                          borderRadius:
                            j === 0
                              ? '14px 4px 4px 4px'
                              : j === 1
                                ? '4px 14px 4px 4px'
                                : j === 2
                                  ? '4px 4px 4px 14px'
                                  : '4px 4px 14px 4px',
                        }}
                      >
                        <ItemImage src={it.imageUrl} alt={it.name} fit="cover" />
                      </div>
                    ))}
                    {itemsWithData.length === 3 && (
                      <span
                        className="flex items-center justify-center text-[10px]"
                        style={{
                          borderRadius: '4px 4px 14px 4px',
                          background: 'rgba(255,255,255,0.07)',
                          border: '1px dashed rgba(255,255,255,0.2)',
                          color: M.ghost,
                        }}
                      >
                        +
                      </span>
                    )}
                    {itemsWithData.length === 0 && (
                      <span
                        className="flex items-center justify-center text-[10px]"
                        style={{
                          gridColumn: '1 / 3',
                          gridRow: '1 / 3',
                          borderRadius: 12,
                          background: 'rgba(255,255,255,0.05)',
                          border: '1px dashed rgba(255,255,255,0.18)',
                          color: M.ghost,
                        }}
                      >
                        no closet items
                      </span>
                    )}
                  </div>

                  <div className="min-w-0 flex-1">
                    <div
                      className="text-[15.5px] font-semibold text-white"
                      style={{ letterSpacing: '-0.2px' }}
                    >
                      {outfit.name ?? 'Outfit'}
                    </div>
                    {outfit.occasion && (
                      <div className="mt-[3px] text-[12px]" style={{ color: M.faint }}>
                        {outfit.occasion}
                      </div>
                    )}
                    {outfit.recommendedItems && outfit.recommendedItems.length > 0 && (
                      <div className="mt-2 flex items-center gap-1.5 text-[11.5px]" style={{ color: 'var(--mint)' }}>
                        <StylistMark size={11} /> Add {outfit.recommendedItems[0].name.toLowerCase()} to finish
                      </div>
                    )}
                  </div>

                  {/* Like — local only ("Saved on this device"). */}
                  <RoundBtn
                    size={32}
                    on={isLiked}
                    aria-label={isLiked ? 'Unlike outfit' : 'Like outfit'}
                    aria-pressed={isLiked}
                    title={isLiked ? 'Saved on this device' : 'Save on this device'}
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
                    icon={<Icon name="InterfaceHeart02" size={15} />}
                  />
                </div>
              );
            })}
          </div>
        )}
      </div>

      <BottomNavBar activeRoute="/outfits" />
    </AppShell>
  );
}
