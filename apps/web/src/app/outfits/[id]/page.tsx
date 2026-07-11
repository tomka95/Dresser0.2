'use client';

/**
 * /outfits/[id] — outfit detail, wired to the real outfits backend.
 *
 * The outfit is a real saved_outfits row (from the store, hydrated by GET
 * /outfits); item rows are real closet items; the heart persists server-side;
 * "Wearing this" posts the real worn feedback (/outfits/feedback) and Remove
 * unsaves the row. Swap hands off to the stylist, which owns the swap loop.
 */

import { useEffect, useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import { Check } from 'lucide-react';

import { useRequireAuth } from '@/lib/auth/useRequireAuth';
import { sendOutfitFeedback } from '@/lib/api/outfitFeedback';
import { useClosetStore } from '@/stores/useClosetStore';
import { useOutfitsStore } from '@/stores/useOutfitsStore';
import { AppShell } from '@/components/layout/AppShell';
import { ItemImage } from '@/components/ui/ItemImage';
import { Btn, Icon, M, RoundBtn, StateBlock, StylistMark, TopBar } from '@/components/ds';

interface OutfitDetailPageProps {
  params: { id: string };
}

export default function OutfitDetailPage({ params }: OutfitDetailPageProps) {
  const router = useRouter();
  const { session, loading } = useRequireAuth();
  const isAuth = !!session;

  const outfits = useOutfitsStore((state) => state.outfits);
  const fetchOutfits = useOutfitsStore((state) => state.fetchOutfits);
  const outfitsLoading = useOutfitsStore((state) => state.isLoading);
  const likedOutfits = useOutfitsStore((state) => state.likedOutfits);
  const toggleLike = useOutfitsStore((state) => state.toggleLike);
  const unsave = useOutfitsStore((state) => state.unsave);

  const closetItems = useClosetStore((state) => state.items);
  const fetchClosetItems = useClosetStore((state) => state.fetchItems);
  const hasFetchedItems = useClosetStore((state) => state.hasFetchedItems);

  const [actionNote, setActionNote] = useState<string | null>(null);

  useEffect(() => {
    if (!isAuth) return;
    if (outfits.length === 0 && !outfitsLoading) fetchOutfits();
    if (!hasFetchedItems) fetchClosetItems();
  }, [isAuth, outfits.length, outfitsLoading, fetchOutfits, hasFetchedItems, fetchClosetItems]);

  const outfit = outfits.find((o) => o.id === params.id);
  const liked = outfit ? likedOutfits.includes(outfit.id) : false;

  const closetMap = useMemo(() => new Map(closetItems.map((i) => [i.id, i])), [closetItems]);
  const outfitItems = (outfit?.items ?? [])
    .map((id) => closetMap.get(id))
    .filter((i): i is NonNullable<typeof i> => !!i);

  if (loading || !isAuth) return null;

  if (!outfit && !outfitsLoading) {
    return (
      <AppShell scroll={false}>
        <div style={{ padding: '52px 20px 0' }}>
          <TopBar title="Outfit" onBack={() => router.push('/outfits')} />
        </div>
        <div className="absolute inset-0 flex items-center justify-center">
          <StateBlock
            icon={
              /* eslint-disable-next-line @next/next/no-img-element */
              <img
                src="/9.png"
                alt=""
                style={{ width: 34, opacity: 0.9, filter: 'brightness(3) grayscale(1)' }}
                aria-hidden
              />
            }
            title="This look is gone"
            sub="It was removed, or the link is stale. Your lookbook has the rest."
            cta={
              <Btn variant="primary" size="md" onClick={() => router.push('/outfits')}>
                Back to Lookbook
              </Btn>
            }
          />
        </div>
      </AppShell>
    );
  }

  if (!outfit) return null;

  const flash = (text: string) => {
    setActionNote(text);
    setTimeout(() => setActionNote(null), 2500);
  };

  const its = outfitItems;

  return (
    <AppShell>
      <div style={{ padding: '52px 20px 0' }}>
        <TopBar
          title={outfit.name ?? 'Outfit'}
          sub={outfit.occasion ? `${outfit.occasion} · ${its.length} from your closet` : undefined}
          onBack={() => router.push('/outfits')}
          right={
            <RoundBtn
              size={40}
              on={liked}
              aria-label={liked ? 'Unlike outfit' : 'Like outfit'}
              aria-pressed={liked}
              title={liked ? 'Liked' : 'Like this look'}
              style={{ borderRadius: 14 }}
              onClick={() => void toggleLike(outfit.id)}
              icon={<Icon name="InterfaceHeart02" size={17} />}
            />
          }
        />
      </div>

      <div style={{ padding: '10px 20px 40px' }}>
        {/* Image grid */}
        {its.length > 0 ? (
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: '1.4fr 1fr',
              gridTemplateRows: '150px 150px',
              gap: 6,
            }}
          >
            {its[0] && (
              <div
                className="overflow-hidden"
                style={{ gridRow: '1 / 3', borderRadius: '24px 8px 8px 24px', border: '1px solid rgba(255,255,255,0.1)' }}
              >
                <ItemImage src={its[0].imageUrl} alt={its[0].name} fit="cover" />
              </div>
            )}
            {its[1] && (
              <div
                className="overflow-hidden"
                style={{ borderRadius: '8px 24px 8px 8px', border: '1px solid rgba(255,255,255,0.1)' }}
              >
                <ItemImage src={its[1].imageUrl} alt={its[1].name} fit="cover" />
              </div>
            )}
            {its[2] && (
              <div
                className="relative overflow-hidden"
                style={{ borderRadius: '8px 8px 24px 8px', border: '1px solid rgba(255,255,255,0.1)' }}
              >
                <ItemImage src={its[2].imageUrl} alt={its[2].name} fit="cover" />
                {its.length > 3 && (
                  <span
                    className="absolute text-[11px] font-semibold text-white"
                    style={{
                      right: 8,
                      bottom: 8,
                      padding: '4px 10px',
                      borderRadius: 999,
                      background: 'rgba(0,0,0,0.55)',
                      backdropFilter: 'blur(8px)',
                      WebkitBackdropFilter: 'blur(8px)',
                    }}
                  >
                    +{its.length - 3} more
                  </span>
                )}
              </div>
            )}
          </div>
        ) : (
          <p className="m-0 text-[13.5px] text-white/50">
            None of this look&rsquo;s items are in your closet anymore.
          </p>
        )}

        {/* AI note — the composer's real rationale when it has one. */}
        <div style={{ ...M.ai(22), padding: '14px 16px', marginTop: 14 }} className="flex gap-3">
          <span style={{ color: 'var(--mint)', marginTop: 2 }}>
            <StylistMark size={14} />
          </span>
          <div className="text-[13px]" style={{ color: M.soft, lineHeight: 1.55 }}>
            {outfit.rationale
              ? outfit.rationale
              : its.length > 0
                ? `${its.length} piece${its.length === 1 ? '' : 's'} from your closet${outfit.occasion ? `, styled for ${outfit.occasion.toLowerCase()}` : ''}.`
                : 'These pieces are no longer in your closet, so Tailor can’t restyle this look.'}
          </div>
        </div>

        {/* Item rows — tap the row to open the piece; the swap glyph routes to
            the stylist (which owns the real swap loop). */}
        {its.length > 0 && (
          <div className="mt-3.5 flex flex-col gap-2.5">
            {its.map((item) => (
              <div
                key={item.id}
                className="flex w-full items-center gap-3 rounded-[16px] p-2.5"
                style={{ background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.08)' }}
              >
                <button
                  type="button"
                  onClick={() => router.push(`/closet/${item.id}`)}
                  className="flex min-w-0 flex-1 items-center gap-3 text-left"
                >
                  <div className="shrink-0 overflow-hidden rounded-[10px]" style={{ width: 40, height: 48 }}>
                    <ItemImage src={item.imageUrl} alt={item.name} fit="cover" />
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="text-[13.5px] font-semibold text-white">{item.name}</div>
                    {item.brand && (
                      <div
                        className="font-accent uppercase"
                        style={{ color: M.faint, fontSize: 11, letterSpacing: '0.5px' }}
                      >
                        {item.brand}
                      </div>
                    )}
                  </div>
                </button>
                <button
                  type="button"
                  aria-label={`Swap ${item.name} — ask the stylist`}
                  title="Swap this piece with the stylist"
                  onClick={() => router.push('/chat')}
                  className="flex shrink-0 items-center justify-center rounded-full text-white/45 transition-colors active:text-white/80"
                  style={{ width: 34, height: 34 }}
                >
                  <Icon name="ArrowArrowsReload01" size={15} />
                </button>
              </div>
            ))}
          </div>
        )}

        {actionNote && (
          <p
            className="mt-4 rounded-xl px-3 py-2 text-center text-[12.5px]"
            style={{ background: 'var(--tr-10)', color: 'rgba(255,255,255,0.75)' }}
            role="status"
          >
            {actionNote}
          </p>
        )}
      </div>

      {/* Bottom action bar — real, persisted actions. */}
      <div
        className="fixed bottom-0 left-0 right-0 z-40 mx-auto flex max-w-[430px] gap-3"
        style={{ padding: '16px 20px 26px', background: 'linear-gradient(to top, rgba(30,30,30,0.98), transparent)' }}
      >
        <Btn
          variant="glass"
          size="lg"
          onClick={async () => {
            await unsave(outfit.id);
            router.push('/outfits');
          }}
          style={{ width: 130 }}
        >
          Remove
        </Btn>
        <Btn
          variant="mint"
          size="lg"
          fullWidth
          icon={<Check size={16} />}
          onClick={async () => {
            const ack = await sendOutfitFeedback({
              feedback: 'worn',
              savedOutfitId: outfit.id,
            });
            flash(ack ? 'Marked as worn — Tailor learns from this' : 'Couldn’t record that right now');
          }}
        >
          Wearing this
        </Btn>
        <Btn
          variant="glass"
          size="lg"
          aria-label="Swap pieces with the stylist"
          title="Swap pieces with the stylist"
          icon={<Icon name="ArrowArrowsReload01" size={18} />}
          onClick={() => router.push('/chat')}
          style={{ width: 54, padding: 0 }}
        />
      </div>
    </AppShell>
  );
}
