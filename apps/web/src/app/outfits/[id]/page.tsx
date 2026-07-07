'use client';

/**
 * /outfits/[id] — outfit detail (the Home AI-suggestion destination), design restyle.
 * FRONTEND-ONLY composition: the outfit comes from the MOCK suggestions store,
 * item rows use REAL closet items, the "finish the look" strip is the mock shop
 * catalog, and Save / Wear today are LOCAL actions (no outfit backend yet) — the
 * microcopy says so ("Saved on this device" / "wear history coming soon").
 */

import { useEffect, useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import { Check } from 'lucide-react';

import { useRequireAuth } from '@/lib/auth/useRequireAuth';
import { useClosetStore } from '@/stores/useClosetStore';
import { useOutfitsStore } from '@/stores/useOutfitsStore';
import { AppShell } from '@/components/layout/AppShell';
import { ItemImage } from '@/components/ui/ItemImage';
import { Btn, Icon, M, RoundBtn, StateBlock, StylistMark, TopBar } from '@/components/ds';
import { SHOP_PRODUCTS } from '@/lib/mock/shop';

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

  const closetItems = useClosetStore((state) => state.items);
  const fetchClosetItems = useClosetStore((state) => state.fetchItems);
  const hasFetchedItems = useClosetStore((state) => state.hasFetchedItems);

  const [actionNote, setActionNote] = useState<string | null>(null);

  useEffect(() => {
    if (!isAuth) return;
    if (outfits.length === 0 && !outfitsLoading) fetchOutfits({ limit: 3 });
    if (!hasFetchedItems) fetchClosetItems();
  }, [isAuth, outfits.length, outfitsLoading, fetchOutfits, hasFetchedItems, fetchClosetItems]);

  const outfit = outfits.find((o) => o.id === params.id);
  const liked = outfit ? likedOutfits.includes(outfit.id) : false;

  const closetMap = useMemo(() => new Map(closetItems.map((i) => [i.id, i])), [closetItems]);
  const outfitItems = (outfit?.items ?? [])
    .map((id) => closetMap.get(id))
    .filter((i): i is NonNullable<typeof i> => !!i);
  const shopAdd = SHOP_PRODUCTS[1];

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
            sub="It was regenerated away, or the link is stale. Your lookbook has the rest."
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
              aria-label={liked ? 'Saved on this device' : 'Save on this device'}
              aria-pressed={liked}
              title={liked ? 'Saved on this device' : 'Save on this device'}
              style={{ borderRadius: 14 }}
              onClick={() => toggleLike(outfit.id)}
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
            None of this look&rsquo;s items are in your closet yet.
          </p>
        )}

        {/* AI note */}
        <div style={{ ...M.ai(22), padding: '14px 16px', marginTop: 14 }} className="flex gap-3">
          <span style={{ color: 'var(--mint)', marginTop: 2 }}>
            <StylistMark size={14} />
          </span>
          <div className="text-[13px]" style={{ color: M.soft, lineHeight: 1.55 }}>
            {its.length > 0
              ? `${its.length} piece${its.length === 1 ? '' : 's'} from your closet${outfit.occasion ? `, styled for ${outfit.occasion.toLowerCase()}` : ''}.`
              : 'Add these pieces to your closet and Tailor will style around them.'}
          </div>
        </div>

        {/* Item rows */}
        {its.length > 0 && (
          <div className="mt-3.5 flex flex-col gap-2.5">
            {its.map((item) => (
              <button
                key={item.id}
                type="button"
                onClick={() => router.push(`/closet/${item.id}`)}
                className="flex w-full items-center gap-3 rounded-[16px] p-2.5 text-left"
                style={{ background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.08)' }}
              >
                <div className="shrink-0 overflow-hidden rounded-[10px]" style={{ width: 40, height: 48 }}>
                  <ItemImage src={item.imageUrl} alt={item.name} fit="cover" />
                </div>
                <div className="flex-1">
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
                <span
                  className="rounded-full"
                  style={{ width: 8, height: 8, background: 'var(--mint)', boxShadow: '0 0 0 3px rgba(75,226,214,0.16)' }}
                  title="In your closet"
                  aria-hidden
                />
              </button>
            ))}
          </div>
        )}

        {/* Finish the look — actionable (mock catalog). */}
        <div className="mt-3.5 rounded-[16px] p-3" style={{ ...M.ai(16) }}>
          <div className="mb-2.5 flex items-center gap-2">
            <span style={{ color: 'var(--mint)' }}>
              <StylistMark size={14} />
            </span>
            <span className="text-[13.5px] font-semibold text-white">Finish the look</span>
          </div>
          <div className="flex items-center gap-3">
            <div className="shrink-0 overflow-hidden rounded-[9px]" style={{ width: 50, height: 62 }}>
              <ItemImage src={shopAdd.img} alt={shopAdd.name} fit="cover" />
            </div>
            <div className="flex-1">
              <div className="text-[14px] font-semibold text-white">{shopAdd.name}</div>
              <div className="text-[12px]" style={{ color: M.faint }}>
                {shopAdd.brand} · ${shopAdd.price}
              </div>
            </div>
            <Btn variant="mint" size="sm" onClick={() => router.push(`/shop/${shopAdd.id}`)}>
              View
            </Btn>
          </div>
        </div>

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

      {/* Bottom action bar — LOCAL only (honest copy). */}
      <div
        className="fixed bottom-0 left-0 right-0 z-40 mx-auto flex max-w-[430px] gap-3"
        style={{ padding: '16px 20px 26px', background: 'linear-gradient(to top, rgba(30,30,30,0.98), transparent)' }}
      >
        <Btn
          variant="glass"
          size="lg"
          onClick={() => {
            if (!liked) toggleLike(outfit.id);
            flash('Saved on this device');
          }}
          style={{ width: 130 }}
        >
          Save
        </Btn>
        <Btn
          variant="mint"
          size="lg"
          fullWidth
          icon={<Check size={16} />}
          onClick={() => flash('Marked as today’s look — wear history is coming soon')}
        >
          Wearing this
        </Btn>
      </div>
    </AppShell>
  );
}
