'use client';

import React, { useEffect, useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import { Search } from 'lucide-react';

import { useRequireAuth } from '@/lib/auth/useRequireAuth';
import { useClosetStore } from '@/stores/useClosetStore';
import { suggestShopItems, type ShopItem } from '@/lib/api/shop';
import { AppShell } from '@/components/layout/AppShell';
import { BottomNavBar } from '@/components/layout/BottomNavBar';
import { Spark } from '@/components/ui/Spark';
import { SectionHeader } from '@/components/ui/SectionHeader';
import { SearchBarDark } from '@/components/ui/SearchBarDark';
import { DarkBadge } from '@/components/ui/DarkBadge';
import { EmptyState } from '@/components/ui/EmptyState';
import { ItemTile } from '@/components/closet/ItemTile';

const SCOPES = ['All', 'My closet', 'Shop', 'Outfits'] as const;
type Scope = (typeof SCOPES)[number];

export default function SearchPage() {
  const router = useRouter();
  const { status } = useRequireAuth();
  const isAuth = status === 'authenticated';

  const [query, setQuery] = useState('');
  const [scopeIndex, setScopeIndex] = useState(0); // default "All"
  const scope: Scope = SCOPES[scopeIndex];

  const items = useClosetStore((s) => s.items);
  const fetchItems = useClosetStore((s) => s.fetchItems);
  const hasFetchedItems = useClosetStore((s) => s.hasFetchedItems);

  // suggestShopItems is MOCK — no backend product-search/recommendation endpoint yet.
  // TODO: shop suggestions are mock — swap suggestShopItems() for a real endpoint when available.
  const [shopItems, setShopItems] = useState<ShopItem[]>([]);

  useEffect(() => {
    if (!isAuth) return;
    if (!hasFetchedItems) fetchItems();
  }, [isAuth, hasFetchedItems, fetchItems]);

  useEffect(() => {
    if (!isAuth) return;
    let active = true;
    suggestShopItems(query)
      .then((res) => {
        if (active) setShopItems(res);
      })
      .catch(() => {
        if (active) setShopItems([]);
      });
    return () => {
      active = false;
    };
  }, [isAuth, query]);

  const closetMatches = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return items;
    return items.filter((it) => {
      const name = (it.name || '').toLowerCase();
      const brand = (it.brand || '').toLowerCase();
      return name.includes(q) || brand.includes(q);
    });
  }, [items, query]);

  if (status === 'loading' || !isAuth) {
    return (
      <AppShell contentClassName="px-6 pt-12">
        <div className="h-10 w-40 rounded-xl bg-white/5 animate-pulse" />
      </AppShell>
    );
  }

  const showCloset = scope !== 'Shop';
  const showShop = scope !== 'My closet';
  const showOutfits = scope === 'Outfits';

  const noCloset = query.trim() !== '' && closetMatches.length === 0;
  const showEmpty = noCloset && scope !== 'Shop' && !showOutfits;

  return (
    <AppShell contentClassName="px-6 pt-12 pb-[120px]">
      {/* Title */}
      <h1 className="text-white m-0" style={{ fontSize: 30, fontWeight: 700 }}>
        Search
      </h1>

      {/* Search input */}
      <div className="mt-4">
        <SearchBarDark
          value={query}
          onChange={setQuery}
          placeholder="Search clothes, brands, looks…"
        />
      </div>

      {/* Scope chips */}
      <div className="flex gap-2.5 mt-[18px] overflow-x-auto -mx-6 px-6 pb-1">
        {SCOPES.map((s, i) => (
          <DarkBadge
            key={s}
            interactive
            selected={scopeIndex === i}
            onClick={() => setScopeIndex(i)}
          >
            {s}
          </DarkBadge>
        ))}
      </div>

      {/* Outfits scope — mock, coming soon */}
      {showOutfits && (
        <p className="mt-7" style={{ color: 'rgba(255,255,255,0.55)', fontSize: 14 }}>
          {/* TODO: outfit search is not backed — outfits are mock */}
          Outfit search is coming soon.
        </p>
      )}

      {/* In your closet */}
      {showCloset && !showOutfits && (
        <div className="mt-7">
          <SectionHeader
            title="In your closet"
            action={`${closetMatches.length} items`}
          />
          {closetMatches.length > 0 && (
            <div className="grid grid-cols-2 gap-[14px] mt-3.5">
              {closetMatches.map((item) => (
                <ItemTile
                  key={item.id}
                  item={{
                    id: item.id,
                    name: item.name,
                    brand: item.brand,
                    imageUrl: item.imageUrl,
                  }}
                  onClick={(id) => router.push(`/closet/${id}`)}
                />
              ))}
            </div>
          )}
        </div>
      )}

      {/* Empty results */}
      {showEmpty && (
        <div className="mt-9">
          <EmptyState
            icon={<Search />}
            title="No matches"
            body={
              'We couldn’t find “' +
              query +
              '” in your closet. Try a different term or shop for it.'
            }
            ctaLabel="Shop this instead"
            ctaIcon={<span style={{ color: 'var(--mint)' }}>✦</span>}
            onCta={() => setScopeIndex(SCOPES.indexOf('Shop'))}
          />
        </div>
      )}

      {/* Shop to complete the look */}
      {showShop && !showOutfits && (
        <div className="mt-9">
          <div className="flex items-center gap-2.5">
            <Spark size={26} />
            <h2 className="text-white m-0" style={{ fontSize: 20, fontWeight: 600 }}>
              Shop to complete the look
            </h2>
          </div>
          {/* TODO: shop suggestions are mock — not backed by a real endpoint */}
          <div className="grid grid-cols-2 gap-[14px] mt-3.5">
            {shopItems.map((shop) => (
              <div
                key={shop.id}
                className="relative rounded-2xl overflow-hidden aspect-[3/4]"
                style={{
                  background: 'rgba(255,255,255,0.06)',
                  border: '1px solid rgba(255,255,255,0.08)',
                }}
              >
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={shop.imageUrl}
                  alt={shop.name}
                  loading="lazy"
                  className="w-full h-full object-cover"
                />
                <div className="absolute inset-0" style={{ background: 'var(--grad-photo-fade)' }} />
                {/* SHOP pill */}
                <span
                  className="absolute top-2.5 left-2.5 rounded-full"
                  style={{
                    background: 'var(--mint)',
                    color: '#06403d',
                    fontSize: 10,
                    fontWeight: 700,
                    letterSpacing: '0.4px',
                    padding: '3px 8px',
                  }}
                >
                  SHOP
                </span>
                <div className="absolute left-3 right-3 bottom-2.5">
                  <div className="text-white font-semibold leading-tight" style={{ fontSize: 14 }}>
                    {shop.name}
                  </div>
                  <div style={{ color: 'rgba(255,255,255,0.7)', fontSize: 12 }}>
                    {shop.brand} · ${shop.price}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      <BottomNavBar active="search" />
    </AppShell>
  );
}
