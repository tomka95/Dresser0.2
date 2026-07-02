'use client';

/**
 * /search — unified search across the owned closet (REAL items, filtered
 * client-side) and shoppable suggestions (MOCK catalog — no shop backend yet).
 * Scope chips: All / My closet / Shop / Outfits.
 */

import { useEffect, useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import { Search as SearchIcon } from 'lucide-react';
import { useRequireAuth } from '@/lib/auth/useRequireAuth';
import { useClosetStore } from '@/stores/useClosetStore';
import { useOutfitsStore } from '@/stores/useOutfitsStore';
import { AppShell } from '@/components/layout/AppShell';
import { BottomNavBar } from '@/components/layout/BottomNavBar';
import { ItemImage } from '@/components/ui/ItemImage';
import {
  DSBadge,
  DSButton,
  DSSearchBar,
  ItemTile,
  SectionHeader,
  Spark,
} from '@/components/ds';
import { SHOP_PRODUCTS } from '@/lib/mock/shop';

const SCOPES = ['All', 'My closet', 'Shop', 'Outfits'] as const;
type Scope = (typeof SCOPES)[number];

export default function SearchPage() {
  const router = useRouter();
  const { session, loading } = useRequireAuth();
  const isAuth = !!session;

  const [query, setQuery] = useState('');
  const [scope, setScope] = useState<Scope>('All');

  const items = useClosetStore((state) => state.items);
  const fetchItems = useClosetStore((state) => state.fetchItems);
  const hasFetchedItems = useClosetStore((state) => state.hasFetchedItems);
  const outfits = useOutfitsStore((state) => state.outfits);

  useEffect(() => {
    if (isAuth && !hasFetchedItems) {
      fetchItems();
    }
  }, [isAuth, hasFetchedItems, fetchItems]);

  const q = query.trim().toLowerCase();

  const closetMatches = useMemo(() => {
    if (!q) return items;
    return items.filter(
      (item) =>
        item.name.toLowerCase().includes(q) ||
        item.brand?.toLowerCase().includes(q) ||
        item.color?.toLowerCase().includes(q) ||
        item.category.toLowerCase().includes(q)
    );
  }, [items, q]);

  const shopMatches = useMemo(() => {
    if (!q) return SHOP_PRODUCTS;
    return SHOP_PRODUCTS.filter(
      (p) => p.name.toLowerCase().includes(q) || p.brand.toLowerCase().includes(q)
    );
  }, [q]);

  const outfitMatches = useMemo(() => {
    if (!q) return outfits;
    return outfits.filter(
      (o) => o.name?.toLowerCase().includes(q) || o.occasion?.toLowerCase().includes(q)
    );
  }, [outfits, q]);

  if (loading || !isAuth) {
    return null;
  }

  const showCloset = scope === 'All' || scope === 'My closet';
  const showShop = scope === 'All' || scope === 'Shop';
  const showOutfits = scope === 'Outfits';

  const nothingFound =
    q.length > 0 &&
    (!showCloset || closetMatches.length === 0) &&
    (!showShop || shopMatches.length === 0) &&
    (!showOutfits || outfitMatches.length === 0);

  return (
    <AppShell>
      <div style={{ padding: '52px 24px 120px' }}>
        <h1 className="m-0 mb-4 text-[30px] font-bold tracking-[-0.5px] text-white">Search</h1>
        <div className="mb-4">
          <DSSearchBar dark placeholder="Search clothes, brands, looks…" value={query} onChange={setQuery} />
        </div>
        <div className="mb-[22px] flex gap-2">
          {SCOPES.map((s) => (
            <DSBadge
              key={s}
              dark
              interactive
              selected={scope === s}
              className="text-[13px]"
              style={{ padding: '8px 14px' }}
              role="button"
              tabIndex={0}
              onClick={() => setScope(s)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') setScope(s);
              }}
            >
              {s}
            </DSBadge>
          ))}
        </div>

        {nothingFound ? (
          // Empty search — offer the shop pivot.
          <div className="flex flex-col items-center px-4 pt-16 text-center">
            <div
              className="mb-[22px] flex items-center justify-center rounded-full"
              style={{
                width: 96,
                height: 96,
                background: 'var(--tr-10)',
                border: '1px solid var(--tr-20)',
                color: 'rgba(255,255,255,0.85)',
              }}
            >
              <SearchIcon size={40} strokeWidth={1.8} />
            </div>
            <h2 className="m-0 mb-2.5 text-[22px] font-bold tracking-[-0.3px] text-white">No matches</h2>
            <p className="mx-auto mb-6 max-w-[280px] text-[14.5px] leading-relaxed text-white/[0.65]">
              We couldn&rsquo;t find &ldquo;{query.trim()}&rdquo; in your closet. Try a different term or
              shop for it.
            </p>
            <DSButton
              variant="light"
              pill
              leftIcon={<span style={{ color: 'var(--mint)' }}>✦</span>}
              style={{ height: 48, padding: '0 26px' }}
              onClick={() => setScope('Shop')}
            >
              Shop this instead
            </DSButton>
          </div>
        ) : (
          <>
            {showCloset && closetMatches.length > 0 && (
              <>
                <SectionHeader
                  dark
                  title="In your closet"
                  action={`${closetMatches.length} item${closetMatches.length === 1 ? '' : 's'}`}
                />
                <div className="mb-[26px] mt-3.5 grid grid-cols-2 gap-3.5">
                  {closetMatches.slice(0, scope === 'My closet' ? undefined : 4).map((it) => (
                    <ItemTile
                      key={it.id}
                      name={it.name}
                      brand={it.brand}
                      imageUrl={it.imageUrl}
                      onClick={() => router.push(`/closet/${it.id}`)}
                    />
                  ))}
                </div>
              </>
            )}

            {showCloset && closetMatches.length === 0 && q.length === 0 && items.length === 0 && (
              <p className="mb-6 text-[13.5px] text-white/50">
                Your closet is empty — add items and they&rsquo;ll show up here.
              </p>
            )}

            {showOutfits && (
              <>
                <SectionHeader
                  dark
                  title="Outfits"
                  action={`${outfitMatches.length} match${outfitMatches.length === 1 ? '' : 'es'}`}
                />
                <div className="mb-[26px] mt-3.5 flex flex-col gap-3">
                  {outfitMatches.length === 0 ? (
                    <p className="text-[13.5px] text-white/50">
                      No outfits yet — generate some on the Outfits screen.
                    </p>
                  ) : (
                    outfitMatches.map((o) => (
                      <button
                        key={o.id}
                        type="button"
                        onClick={() => router.push('/outfits')}
                        className="flex w-full items-center justify-between rounded-2xl px-4 py-3.5 text-left"
                        style={{ background: 'var(--tr-10)', border: '1px solid var(--tr-20)' }}
                      >
                        <span className="text-[15px] font-semibold text-white">{o.name ?? 'Outfit'}</span>
                        <span className="text-[13px] text-white/60">{o.occasion}</span>
                      </button>
                    ))
                  )}
                </div>
              </>
            )}

            {showShop && shopMatches.length > 0 && (
              <>
                <div className="mb-3.5 flex items-center gap-2">
                  <Spark size={26} />
                  <span className="text-[20px] font-semibold text-white">Shop to complete the look</span>
                </div>
                <div className="grid grid-cols-2 gap-3.5">
                  {shopMatches.map((p) => (
                    <button
                      key={p.id}
                      type="button"
                      onClick={() => router.push(`/shop/${p.id}`)}
                      className="relative overflow-hidden rounded-2xl border-none p-0 text-left"
                      style={{ aspectRatio: '3/4', border: '1px solid rgba(255,255,255,0.1)' }}
                    >
                      <ItemImage src={p.img} alt={p.name} fit="cover" />
                      <div className="pointer-events-none absolute inset-0" style={{ background: 'var(--grad-photo-fade)' }} aria-hidden />
                      <span
                        className="absolute left-2.5 top-2.5 rounded-full font-bold"
                        style={{
                          fontSize: 10,
                          letterSpacing: '0.4px',
                          color: 'var(--brand-teal)',
                          background: 'var(--mint)',
                          padding: '3px 8px',
                        }}
                      >
                        SHOP
                      </span>
                      <div className="absolute bottom-2.5 left-3 right-3">
                        <div className="text-[14px] font-semibold text-white">{p.name}</div>
                        <div className="text-[12px] text-white/70">
                          {p.brand} · ${p.price}
                        </div>
                      </div>
                    </button>
                  ))}
                </div>
              </>
            )}
          </>
        )}
      </div>

      <BottomNavBar activeRoute="/search" />
    </AppShell>
  );
}
