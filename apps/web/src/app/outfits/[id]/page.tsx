'use client';

/**
 * /outfits/[id] — outfit detail (the Home AI-suggestion destination).
 * FRONTEND-ONLY composition: the outfit comes from the MOCK suggestions store,
 * item rows use REAL closet items, the "finish the look" strip is the mock shop
 * catalog, and Save / Wear today are local actions (no outfit backend yet).
 */

import { useEffect, useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import { Heart } from 'lucide-react';
import { useRequireAuth } from '@/lib/auth/useRequireAuth';
import { useClosetStore } from '@/stores/useClosetStore';
import { useOutfitsStore } from '@/stores/useOutfitsStore';
import { AppShell } from '@/components/layout/AppShell';
import { ItemImage } from '@/components/ui/ItemImage';
import { DSButton, Spark, TopBar } from '@/components/ds';
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
  const heroImage = outfitItems.find((i) => i.imageUrl)?.imageUrl;
  const shopAdd = SHOP_PRODUCTS[1];

  if (loading || !isAuth) return null;

  if (!outfit && !outfitsLoading) {
    return (
      <AppShell scroll={false}>
        <div className="flex h-full flex-col items-center justify-center px-8 text-center">
          <h1 className="m-0 text-[20px] font-bold text-white">Outfit not found</h1>
          <p className="mb-6 mt-2 text-sm text-white/60">It may have been regenerated away.</p>
          <DSButton variant="light" pill onClick={() => router.push('/outfits')} style={{ height: 48, padding: '0 26px' }}>
            Back to outfits
          </DSButton>
        </div>
      </AppShell>
    );
  }

  if (!outfit) return null;

  const flash = (text: string) => {
    setActionNote(text);
    setTimeout(() => setActionNote(null), 2500);
  };

  return (
    <AppShell>
      {/* Hero */}
      <div className="relative" style={{ height: 300 }}>
        <ItemImage src={heroImage} alt={outfit.name ?? 'Outfit'} fit="cover" emptyLabel="No preview" />
        <div
          className="pointer-events-none absolute inset-0"
          style={{ background: 'linear-gradient(180deg, rgba(0,0,0,0.45) 0%, transparent 35%, rgba(30,30,30,0.96) 100%)' }}
          aria-hidden
        />
        <div className="absolute left-4 right-4" style={{ top: 48 }}>
          <TopBar
            onBack={() => router.push('/outfits')}
            right={
              <button
                type="button"
                aria-label={liked ? 'Unlike' : 'Like'}
                onClick={() => toggleLike(outfit.id)}
                className="flex h-10 w-10 items-center justify-center"
                style={{ color: liked ? 'var(--mint)' : '#fff' }}
              >
                <Heart size={20} fill={liked ? 'currentColor' : 'none'} />
              </button>
            }
          />
        </div>
        <div className="absolute bottom-3.5 left-6 right-6">
          <div className="mb-1.5 flex items-center gap-2 text-[12px] font-semibold" style={{ color: 'var(--mint)' }}>
            <Spark size={22} /> AI styled · for 21°, clear
          </div>
          <h1 className="m-0 text-[27px] font-bold tracking-[-0.4px] text-white">{outfit.name ?? 'Outfit'}</h1>
          <div className="mt-0.5 text-[14px] text-white/[0.65]">
            {outfit.occasion ? `${outfit.occasion} · ` : ''}
            {outfitItems.length} piece{outfitItems.length === 1 ? '' : 's'} from your closet
          </div>
        </div>
      </div>

      <div style={{ padding: '18px 24px 140px' }}>
        {/* Item rows */}
        <div className="flex flex-col gap-2.5">
          {outfitItems.map((item) => (
            <button
              key={item.id}
              type="button"
              onClick={() => router.push(`/closet/${item.id}`)}
              className="flex w-full items-center gap-3.5 rounded-[14px] p-2.5 text-left"
              style={{ background: 'var(--tr-10)', border: '1px solid var(--tr-20)' }}
            >
              <div className="shrink-0 overflow-hidden rounded-[10px]" style={{ width: 56, height: 70 }}>
                <ItemImage src={item.imageUrl} alt={item.name} fit="cover" />
              </div>
              <div className="flex-1">
                <div className="text-[15px] font-semibold text-white">{item.name}</div>
                {item.brand && (
                  <div
                    className="font-accent uppercase"
                    style={{ color: 'rgba(255,255,255,0.55)', fontSize: 12, letterSpacing: '0.4px' }}
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
          {outfitItems.length === 0 && (
            <p className="m-0 text-[13.5px] text-white/50">
              None of this look&rsquo;s items are in your closet yet.
            </p>
          )}
        </div>

        {/* AI recommended addition — actionable (mock catalog). */}
        <div className="mt-3.5 rounded-[14px] p-3" style={{ background: 'var(--grad-ai)', border: '1px solid var(--tr-20)' }}>
          <div className="mb-2.5 flex items-center gap-2">
            <span style={{ color: 'var(--mint)' }}>✦</span>
            <span className="text-[13.5px] font-semibold text-white">Finish the look</span>
          </div>
          <div className="flex items-center gap-3">
            <div className="shrink-0 overflow-hidden rounded-[9px]" style={{ width: 50, height: 62 }}>
              <ItemImage src={shopAdd.img} alt={shopAdd.name} fit="cover" />
            </div>
            <div className="flex-1">
              <div className="text-[14px] font-semibold text-white">{shopAdd.name}</div>
              <div className="text-[12px] text-white/60">
                {shopAdd.brand} · ${shopAdd.price}
              </div>
            </div>
            <button
              type="button"
              onClick={() => router.push(`/shop/${shopAdd.id}`)}
              className="rounded-full border-none font-bold"
              style={{ height: 36, padding: '0 16px', background: 'var(--mint)', color: 'var(--brand-teal)', fontSize: 13 }}
            >
              Add
            </button>
          </div>
        </div>

        {actionNote && (
          <p className="mt-4 rounded-xl px-3 py-2 text-center text-[12.5px]" style={{ background: 'var(--tr-10)', color: 'rgba(255,255,255,0.75)' }}>
            {actionNote}
          </p>
        )}
      </div>

      {/* Bottom action bar */}
      <div
        className="fixed bottom-0 left-0 right-0 z-40 mx-auto flex max-w-[430px] gap-3"
        style={{ padding: '16px 24px 26px', background: 'linear-gradient(to top, rgba(30,30,30,0.98), transparent)' }}
      >
        <DSButton
          variant="outline"
          pill
          className="flex-1"
          style={{ color: '#fff', borderColor: 'var(--tr-20)' }}
          onClick={() => {
            if (!liked) toggleLike(outfit.id);
            flash('Saved to your liked outfits');
          }}
        >
          Save
        </DSButton>
        <DSButton
          variant="light"
          pill
          style={{ flex: 1.5 }}
          onClick={() => flash('Marked as today’s look — wear history is coming soon')}
        >
          Wear today
        </DSButton>
      </div>
    </AppShell>
  );
}
