'use client';

/**
 * /search — unified search (restyle of §6 · F3). NO search backend exists.
 *   - Closet results are REAL: a client-side filter over useClosetStore.
 *   - Shop results are MOCK suggestions (lib/mock/shop) — clearly labeled as
 *     "sample suggestions", NOT the closet-aware ranker (the ranker lives on Home).
 *
 * States: default (recents + browse), results, no-match (shop pivot),
 * closet-empty note, loading, offline.
 */

import { useEffect, useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import { useRequireAuth } from '@/lib/auth/useRequireAuth';
import { useClosetStore } from '@/stores/useClosetStore';
import { useOutfitsStore } from '@/stores/useOutfitsStore';
import { useOnline } from '@/lib/useOnline';
import { AppShell } from '@/components/layout/AppShell';
import { BottomNavBar } from '@/components/layout/BottomNavBar';
import { ItemImage } from '@/components/ui/ItemImage';
import {
  Btn,
  Field,
  Icon,
  ItemTile,
  StateBlock,
  OfflineScreen,
  Sk,
  SkGrid,
  SkList,
  Spark,
  M,
  NAV_CLEAR,
} from '@/components/ds';
import { SHOP_PRODUCTS } from '@/lib/mock/shop';

const SCOPES = ['All', 'My closet', 'Shop', 'Outfits'] as const;
type Scope = (typeof SCOPES)[number];

export default function SearchPage() {
  const router = useRouter();
  const { session, loading } = useRequireAuth('/sign-in', { requireOnboarded: true });
  const isAuth = !!session;
  const online = useOnline();

  const [query, setQuery] = useState('');
  const [scope, setScope] = useState<Scope>('All');

  const items = useClosetStore((s) => s.items);
  const fetchItems = useClosetStore((s) => s.fetchItems);
  const hasFetchedItems = useClosetStore((s) => s.hasFetchedItems);
  const outfits = useOutfitsStore((s) => s.outfits);

  useEffect(() => {
    if (isAuth && !hasFetchedItems) fetchItems();
  }, [isAuth, hasFetchedItems, fetchItems]);

  const q = query.trim().toLowerCase();

  const closetMatches = useMemo(() => {
    if (!q) return items;
    return items.filter(
      (item) =>
        item.name.toLowerCase().includes(q) ||
        item.brand?.toLowerCase().includes(q) ||
        item.color?.toLowerCase().includes(q) ||
        item.category.toLowerCase().includes(q),
    );
  }, [items, q]);

  const shopMatches = useMemo(() => {
    if (!q) return SHOP_PRODUCTS;
    return SHOP_PRODUCTS.filter(
      (p) => p.name.toLowerCase().includes(q) || p.brand.toLowerCase().includes(q),
    );
  }, [q]);

  const outfitMatches = useMemo(() => {
    if (!q) return outfits;
    return outfits.filter(
      (o) => o.name?.toLowerCase().includes(q) || o.occasion?.toLowerCase().includes(q),
    );
  }, [outfits, q]);

  if (loading || !isAuth) return null;

  const showCloset = scope === 'All' || scope === 'My closet';
  const showShop = scope === 'All' || scope === 'Shop';
  const showOutfits = scope === 'Outfits';

  const nothingFound =
    q.length > 0 &&
    (!showCloset || closetMatches.length === 0) &&
    (!showShop || shopMatches.length === 0) &&
    (!showOutfits || outfitMatches.length === 0);

  const header = (
    <>
      <h1 className="m-0 text-[30px] font-bold tracking-[-0.8px] text-white">Search</h1>
      <div className="mt-3.5">
        <Field
          icon={<Icon name="InterfaceSearchMagnifyingGlass" size={17} />}
          value={query}
          onChange={setQuery}
          placeholder="Closet, shop, outfits…"
          right={
            query ? (
              <button
                type="button"
                aria-label="Clear search"
                onClick={() => setQuery('')}
                style={{ color: M.faint }}
              >
                <Icon name="MenuCloseMD" size={15} />
              </button>
            ) : undefined
          }
        />
      </div>
      <div className="flex gap-2 overflow-x-auto pb-0.5 pt-3.5">
        {SCOPES.map((s) => {
          const on = scope === s;
          return (
            <button
              key={s}
              type="button"
              onClick={() => setScope(s)}
              className="shrink-0 rounded-full text-[13px] font-semibold transition-colors"
              style={{
                padding: '7px 14px',
                color: on ? 'var(--brand-teal)' : '#fff',
                background: on ? 'var(--mint)' : 'rgba(255,255,255,0.08)',
                border: on ? '1px solid transparent' : '1px solid rgba(255,255,255,0.14)',
              }}
            >
              {s}
            </button>
          );
        })}
      </div>
    </>
  );

  // Offline — closet is cached client-side, so search still works over it, but
  // signal the degraded state up top.
  return (
    <AppShell>
      <div style={{ padding: `52px 20px ${NAV_CLEAR}px` }}>
        {header}

        <div className="mt-4">
          {!online && !hasFetchedItems ? (
            <OfflineScreen
              context="Search needs your closet loaded. Reconnect to search across it."
              onRetry={() => fetchItems()}
              onBrowseCloset={() => router.push('/closet')}
            />
          ) : !hasFetchedItems ? (
            // Loading — mixed skeleton (grid over list).
            <>
              <Sk w={110} h={11} style={{ margin: '4px 0 12px' }} />
              <SkGrid rows={1} />
              <Sk w={96} h={11} style={{ margin: '18px 0 12px' }} />
              <SkList n={2} />
            </>
          ) : nothingFound ? (
            <StateBlock
              compact
              icon={<Icon name="InterfaceSearchMagnifyingGlass" size={26} />}
              title={`No match for “${query.trim()}”`}
              sub="Nothing in your closet, outfits, or the sample shop. Try a different term."
              cta={
                <Btn
                  variant="glass"
                  size="md"
                  icon={<Spark size={13} />}
                  onClick={() => setScope('Shop')}
                >
                  See shop suggestions
                </Btn>
              }
              cta2={
                <Btn variant="ghost" size="md" onClick={() => setQuery('')}>
                  Clear search
                </Btn>
              }
            />
          ) : q.length === 0 ? (
            // Default — recents + browse chips.
            <DefaultBrowse onPick={setQuery} />
          ) : (
            <>
              {/* In your closet — REAL. */}
              {showCloset && (
                <>
                  {closetMatches.length > 0 ? (
                    <>
                      <SectionLabel>
                        In your closet · {closetMatches.length}
                      </SectionLabel>
                      <div className="mb-6 mt-3 grid grid-cols-2 gap-3.5">
                        {closetMatches
                          .slice(0, scope === 'My closet' ? undefined : 4)
                          .map((it) => (
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
                  ) : items.length === 0 ? (
                    <p className="mb-6 text-[13.5px]" style={{ color: M.faint }}>
                      Your closet is empty — add items and they’ll show up here.
                    </p>
                  ) : null}
                </>
              )}

              {/* Outfits — REAL. */}
              {showOutfits && (
                <>
                  <SectionLabel>Outfits · {outfitMatches.length}</SectionLabel>
                  <div className="mb-6 mt-3 flex flex-col gap-3">
                    {outfitMatches.length === 0 ? (
                      <p className="text-[13.5px]" style={{ color: M.faint }}>
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
                          <span className="text-[15px] font-semibold text-white">
                            {o.name ?? 'Outfit'}
                          </span>
                          <span className="text-[13px]" style={{ color: M.faint }}>
                            {o.occasion}
                          </span>
                        </button>
                      ))
                    )}
                  </div>
                </>
              )}

              {/* From the shop — MOCK. Labeled honestly as sample suggestions. */}
              {showShop && shopMatches.length > 0 && (
                <>
                  <div className="mb-3 mt-1 flex items-baseline justify-between">
                    <SectionLabel>Shop suggestions · {shopMatches.length}</SectionLabel>
                    <span className="text-[11px]" style={{ color: M.ghost }}>
                      samples — not the ranker
                    </span>
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
                        <div
                          className="pointer-events-none absolute inset-0"
                          style={{ background: 'var(--grad-photo-fade)' }}
                          aria-hidden
                        />
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
                          SAMPLE
                        </span>
                        <div className="absolute bottom-2.5 left-3 right-3">
                          <div className="text-[14px] font-semibold text-white">{p.name}</div>
                          <div className="text-[12px]" style={{ color: 'rgba(255,255,255,0.7)' }}>
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
      </div>

      <BottomNavBar activeRoute="/search" />
    </AppShell>
  );
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <div
      className="uppercase"
      style={{ color: M.faint, fontSize: 11, fontWeight: 700, letterSpacing: '0.6px' }}
    >
      {children}
    </div>
  );
}

const RECENTS = ['white sneakers', 'linen', 'dinner outfit'];
const BROWSE = ['Tops', 'Outerwear', 'Under $100', 'Most worn', 'Never worn', 'Liked looks'];

function DefaultBrowse({ onPick }: { onPick: (q: string) => void }) {
  return (
    <div>
      <SectionLabel>Recent</SectionLabel>
      <div className="mt-2 mb-5">
        {RECENTS.map((r) => (
          <button
            key={r}
            type="button"
            onClick={() => onPick(r)}
            className="flex w-full items-center gap-3 py-2.5 text-left"
          >
            <Icon name="ArrowArrowsReload01" size={15} style={{ color: M.ghost }} />
            <span className="flex-1 text-[14px]" style={{ color: M.soft }}>
              {r}
            </span>
          </button>
        ))}
      </div>
      <SectionLabel>Browse</SectionLabel>
      <div className="mt-3 flex flex-wrap gap-2.5">
        {BROWSE.map((c) => (
          <button
            key={c}
            type="button"
            onClick={() => onPick(c)}
            className="rounded-full text-[13px] font-medium"
            style={{
              padding: '7px 14px',
              color: '#fff',
              background: 'rgba(255,255,255,0.08)',
              border: '1px solid rgba(255,255,255,0.14)',
            }}
          >
            {c}
          </button>
        ))}
      </div>
    </div>
  );
}
