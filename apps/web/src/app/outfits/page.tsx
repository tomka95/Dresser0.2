'use client';

/**
 * /outfits — Lookbook, wired to the real outfits backend.
 *
 * Data is GET /outfits (saved_outfits: chat saves, worn Today's Looks, composer
 * generates); "New look" is POST /outfits/generate through the same composer +
 * weather + Style Profile pipeline as Today's Look. Likes persist server-side
 * (PUT/DELETE /outfits/{id}/like). Every card references real closet items —
 * an outfit whose items no longer resolve to the closet is not rendered, and a
 * closet that can't complete a look surfaces the composer's honest gap note.
 */

import { useEffect, useMemo } from 'react';
import { useRouter } from 'next/navigation';
import { Check } from 'lucide-react';

import { track } from '@/lib/analytics';
import { sendOutfitFeedback } from '@/lib/api/outfitFeedback';
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

  // Auth guard — parity with /outfits/[id].
  const { session, loading } = useRequireAuth();
  const isAuth = !!session;

  const outfits = useOutfitsStore((state) => state.outfits);
  const likedOutfits = useOutfitsStore((state) => state.likedOutfits);
  const isLoading = useOutfitsStore((state) => state.isLoading);
  const isGenerating = useOutfitsStore((state) => state.isGenerating);
  const error = useOutfitsStore((state) => state.error);
  const generateNotice = useOutfitsStore((state) => state.generateNotice);
  const fetchOutfits = useOutfitsStore((state) => state.fetchOutfits);
  const generateOutfit = useOutfitsStore((state) => state.generateOutfit);
  const toggleLike = useOutfitsStore((state) => state.toggleLike);

  const closetItems = useClosetStore((state) => state.items);
  const closetLoading = useClosetStore((state) => state.isLoading);
  const fetchClosetItems = useClosetStore((state) => state.fetchItems);

  useEffect(() => {
    if (!isAuth) return;
    track('outfit_suggestions_viewed', { outfit_count: outfits.length });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isAuth]);

  useEffect(() => {
    if (!isAuth) return;
    if (outfits.length === 0 && !isLoading) fetchOutfits();
  }, [isAuth, fetchOutfits, isLoading, outfits.length]);

  useEffect(() => {
    if (!isAuth) return;
    if (closetItems.length === 0 && !closetLoading) fetchClosetItems();
  }, [isAuth, closetItems.length, closetLoading, fetchClosetItems]);

  const closetMap = useMemo(
    () => new Map(closetItems.map((item) => [item.id, item])),
    [closetItems]
  );

  // HONEST RENDERING: a card exists only when its outfit still resolves to at
  // least one real closet item (items can be archived/deleted after a save).
  const renderableOutfits = useMemo(
    () =>
      outfits.filter((outfit) =>
        outfit.items.some((itemId) => closetMap.has(itemId))
      ),
    [outfits, closetMap]
  );

  async function handleGenerate() {
    track('outfit_regenerate_clicked');
    const added = await generateOutfit();
    if (!added) {
      const { error: err } = useOutfitsStore.getState();
      if (err) track('outfit_regenerate_failed', { error: err });
    }
  }

  if (loading || !isAuth) return null;

  const busy = isLoading || closetLoading;
  const showEmpty =
    renderableOutfits.length === 0 && !busy && !isGenerating && !error;

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
            onClick={handleGenerate}
            pending={isGenerating}
          >
            New look
          </Btn>
        </div>

        {/* Honest composer gap — the closet can't complete a look right now. */}
        {generateNotice && (
          <p
            className="mt-3 rounded-xl px-3 py-2 text-[12.5px]"
            style={{ background: 'var(--tr-10)', color: 'rgba(255,255,255,0.75)' }}
            role="status"
          >
            {generateNotice}
          </p>
        )}

        {/* Loading */}
        {busy && renderableOutfits.length === 0 && (
          <div className="mt-4">
            <SkList n={3} />
          </div>
        )}

        {/* Error */}
        {error && renderableOutfits.length === 0 && !busy && (
          <div className="mt-6">
            <ErrorState
              compact
              title="Couldn’t load your looks"
              sub={`${error}. Your closet is safe.`}
              onRetry={() => fetchOutfits()}
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
                <Btn variant="mint" size="md" icon={<StylistMark size={13} />} onClick={handleGenerate}>
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
        {renderableOutfits.length > 0 && (
          <div className="mt-3 flex flex-col gap-3">
            {renderableOutfits.map((outfit) => {
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
                  {/* 2×2 thumb grid — always real closet items (filter above). */}
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

                    {/* Wore it hits the REAL feedback loop (/outfits/feedback);
                        Swap hands off to the stylist, which owns the swap loop. */}
                    <div className="mt-2.5 flex gap-1.5">
                      <Btn
                        variant="mint"
                        size="xs"
                        icon={<Check size={11} />}
                        onClick={(e) => {
                          e.stopPropagation();
                          track('outfit_worn_clicked', { outfit_id: outfit.id });
                          void sendOutfitFeedback({
                            feedback: 'worn',
                            savedOutfitId: outfit.id,
                          });
                        }}
                      >
                        Wore it
                      </Btn>
                      <Btn
                        variant="glass"
                        size="xs"
                        icon={<Icon name="ArrowArrowsReload01" size={11} />}
                        onClick={(e) => {
                          e.stopPropagation();
                          track('outfit_feedback_to_chat', { outfit_id: outfit.id, action: 'swap' });
                          router.push('/chat');
                        }}
                      >
                        Swap
                      </Btn>
                    </div>
                  </div>

                  {/* Like — persisted server-side. */}
                  <RoundBtn
                    size={32}
                    on={isLiked}
                    aria-label={isLiked ? 'Unlike outfit' : 'Like outfit'}
                    aria-pressed={isLiked}
                    title={isLiked ? 'Liked' : 'Like this look'}
                    onClick={(e) => {
                      e.stopPropagation();
                      const wasLiked = isLiked;
                      void toggleLike(outfit.id);
                      track(wasLiked ? 'outfit_unliked' : 'outfit_liked', {
                        outfit_id: outfit.id,
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
