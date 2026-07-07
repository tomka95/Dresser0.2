'use client';

// Closet grid (§3 · C1) — real /closet items: search + category chips + 2-col
// tile grid with favourite hearts + FAB (opens AddItemDrawer). States: populated,
// empty, loading (skeleton — no blank gate), error (retry), filtered-no-match.

import React, { useEffect, useState, useMemo } from 'react';
import { useRouter, usePathname } from 'next/navigation';
import { Plus, X, ScanLine } from 'lucide-react';
import { useRequireAuth } from '@/lib/auth/useRequireAuth';
import { useClosetStore } from '@/stores/useClosetStore';
import { logEvent, startSession } from '@/lib/api/events';
import { AppShell } from '@/components/layout/AppShell';
import { BottomNavBar } from '@/components/layout/BottomNavBar';
import { AddItemDrawer } from '@/components/closet/AddItemDrawer';
import {
  Btn,
  CategoryChips,
  ErrorState,
  Field,
  Icon,
  ItemTile,
  NAV_CLEAR,
  Spark,
  StateBlock,
  SkGrid,
  M,
  type CategoryChipItem,
} from '@/components/ds';

const CATEGORIES: CategoryChipItem[] = [
  { id: 'all', label: 'All' },
  { id: 'top', label: 'Tops' },
  { id: 'bottom', label: 'Bottoms' },
  { id: 'dress', label: 'Dresses' },
  { id: 'outerwear', label: 'Outerwear' },
  { id: 'shoes', label: 'Shoes' },
  { id: 'accessories', label: 'Accessories' },
  { id: 'other', label: 'Other' },
];

export default function ClosetPage() {
  const router = useRouter();
  const pathname = usePathname();
  // Gate on the Supabase session AND onboarding completion.
  const { session, loading: checkingAuth } = useRequireAuth('/sign-in', { requireOnboarded: true });
  const isAuth = !!session;
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedCategory, setSelectedCategory] = useState('all');
  const [drawerOpen, setDrawerOpen] = useState(false);
  // Optimistic overlay over the persisted item.isFavorite (source of truth is the
  // server via updateItem). Only holds ids whose heart was toggled this session.
  const [favOverride, setFavOverride] = useState<Record<string, boolean>>({});

  const items = useClosetStore((state) => state.items);
  const fetchItems = useClosetStore((state) => state.fetchItems);
  const updateItem = useClosetStore((state) => state.updateItem);
  const hasFetchedItems = useClosetStore((state) => state.hasFetchedItems);
  const isLoading = useClosetStore((state) => state.isLoading);
  const error = useClosetStore((state) => state.error);

  useEffect(() => {
    if (isAuth && !hasFetchedItems) {
      fetchItems();
    }
  }, [isAuth, hasFetchedItems, fetchItems]);

  // Emit session_start once per tab session (idempotent).
  useEffect(() => {
    if (isAuth) startSession();
  }, [isAuth]);

  // Persist a favorite toggle server-side (which also server-derives the `favorite`
  // event). Optimistic: flip immediately, revert on failure.
  const toggleFavorite = async (id: string, current: boolean) => {
    const next = !current;
    setFavOverride((f) => ({ ...f, [id]: next }));
    try {
      await updateItem(id, { isFavorite: next, eventSource: 'closet_grid' });
    } catch {
      setFavOverride((f) => ({ ...f, [id]: current })); // revert
    }
  };

  // Filter the REAL closet items by category and search. No mock fallback — an
  // empty result renders the empty state below, never placeholder cards.
  const isFiltering = selectedCategory !== 'all' || searchQuery.trim().length > 0;

  const filteredItems = useMemo(() => {
    let filtered = items;
    if (selectedCategory !== 'all') {
      filtered = filtered.filter((item) => item.category === selectedCategory);
    }
    if (searchQuery.trim()) {
      const query = searchQuery.toLowerCase();
      filtered = filtered.filter(
        (item) =>
          item.name.toLowerCase().includes(query) ||
          item.brand?.toLowerCase().includes(query) ||
          item.category.toLowerCase().includes(query)
      );
    }
    return filtered;
  }, [items, selectedCategory, searchQuery]);

  // Bento layout (§3 · C1) leads the unfiltered closet with a "Most versatile"
  // hero tile — the real most-worn piece, an honest versatility signal. Only when
  // there's a genuine winner (a positive wearCount) and enough pieces to fill the
  // asymmetric row; filtered/search results keep the plain 2-col grid so the
  // no-match lead below stays clean.
  const featured = useMemo(() => {
    if (isFiltering || filteredItems.length < 3) return null;
    let best = filteredItems[0];
    for (const it of filteredItems) {
      if ((it.wearCount ?? 0) > (best.wearCount ?? 0)) best = it;
    }
    return (best.wearCount ?? 0) > 0 ? best : null;
  }, [filteredItems, isFiltering]);

  // With a featured hero: [featured] + [next two stacked] fill the bento row, the
  // remainder flows into the 2-col grid below.
  const bentoTop = featured ? filteredItems.filter((it) => it.id !== featured.id).slice(0, 2) : [];
  const bentoRest = featured
    ? filteredItems.filter((it) => it.id !== featured.id).slice(2)
    : filteredItems;

  // One tile renderer shared by the bento hero, the stacked pair, and the 2-col
  // grid — keeps favourite/click behaviour identical across all three.
  const renderTile = (
    it: (typeof filteredItems)[number],
    opts?: { h?: number; badge?: React.ReactNode },
  ) => {
    const faved = favOverride[it.id] ?? !!it.isFavorite;
    return (
      <ItemTile
        key={it.id}
        name={it.name}
        brand={it.brand}
        imageUrl={it.imageUrl}
        faved={faved}
        h={opts?.h}
        badge={opts?.badge}
        onFav={() => toggleFavorite(it.id, faved)}
        onClick={() => {
          logEvent({ eventType: 'item_view', itemId: it.id, source: 'closet_grid' });
          router.push(`/closet/${it.id}`);
        }}
      />
    );
  };

  if (checkingAuth || !isAuth) {
    return null;
  }

  const closetIsEmpty = hasFetchedItems && !isLoading && !error && items.length === 0;
  // First load with nothing yet: show the grid skeleton (no blank gate).
  const showLoadingSkeleton = !hasFetchedItems && isLoading;
  const totalCount = items.length;
  // Real closet worth from unit prices × quantity — shown only when prices exist,
  // never a fabricated figure.
  const closetWorth = Math.round(
    items.reduce((sum, it) => sum + (it.unitPrice ?? 0) * (it.quantity ?? 1), 0),
  );

  return (
    <AppShell>
      <div style={{ padding: `52px 20px ${NAV_CLEAR}px` }}>
        {/* Header — title + piece count. */}
        <div style={{ display: 'flex', alignItems: 'flex-end', justifyContent: 'space-between' }}>
          <div>
            <h1 className="m-0 text-[30px] font-bold text-white" style={{ letterSpacing: '-0.8px' }}>
              My Closet
            </h1>
            {totalCount > 0 && (
              <div style={{ color: M.faint, fontSize: 13.5, marginTop: 3 }}>
                {totalCount} {totalCount === 1 ? 'piece' : 'pieces'}
                {closetWorth > 0 && ` · worth $${closetWorth.toLocaleString()}`}
              </div>
            )}
          </div>
        </div>

        {/* Search */}
        <div style={{ marginTop: 16 }}>
          <Field
            icon={<Icon name="InterfaceSearchMagnifyingGlass" size={17} />}
            value={searchQuery}
            onChange={setSearchQuery}
            placeholder="Search your closet"
            right={
              searchQuery ? (
                <button
                  type="button"
                  aria-label="Clear search"
                  onClick={() => setSearchQuery('')}
                  className="flex items-center text-white/50 active:scale-90"
                >
                  <X size={16} />
                </button>
              ) : undefined
            }
          />
        </div>

        {/* Category chips */}
        <div style={{ marginTop: 14, marginBottom: 4 }}>
          <CategoryChips items={CATEGORIES} value={selectedCategory} onChange={setSelectedCategory} />
        </div>

        {/* Content — loading skeleton first (no blank gate), then error / empty /
            no-match / populated. */}
        {showLoadingSkeleton ? (
          <div style={{ marginTop: 10 }}>
            <SkGrid rows={3} />
          </div>
        ) : error ? (
          <div style={{ marginTop: 6 }}>
            <ErrorState
              title="Your closet didn't load"
              sub="The rack got stuck. Pull to refresh, or try again."
              onRetry={() => fetchItems()}
            />
          </div>
        ) : closetIsEmpty ? (
          // Empty closet — hanger medallion + primary CTA (header + nav stay around it).
          <div style={{ marginTop: 18 }}>
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
              title="Your closet is empty"
              sub="Add your first pieces and Tailor starts styling with what you actually own."
              cta={
                <Btn variant="primary" size="md" icon={<Plus size={16} strokeWidth={2.4} />} onClick={() => setDrawerOpen(true)}>
                  Add your first item
                </Btn>
              }
              foot="Takes about a minute"
            />
          </div>
        ) : filteredItems.length === 0 ? (
          // Filtered dead end — turn the miss into a shopping lead / clear action.
          <div style={{ marginTop: 12 }}>
            <StateBlock
              compact
              icon={<Icon name="InterfaceSearchMagnifyingGlass" size={26} />}
              title={searchQuery.trim() ? `Nothing matches "${searchQuery.trim()}"` : 'Nothing in this category yet'}
              sub="Not in your closet yet — want Tailor to find one that fits your style?"
              cta={
                <Btn variant="glass" size="md" icon={<Spark size={13} />} onClick={() => router.push('/search')}>
                  Shop this instead
                </Btn>
              }
              cta2={
                (searchQuery || selectedCategory !== 'all') && (
                  <Btn
                    variant="ghost"
                    size="md"
                    onClick={() => {
                      setSearchQuery('');
                      setSelectedCategory('all');
                    }}
                  >
                    Clear search
                  </Btn>
                )
              }
            />
          </div>
        ) : (
          <>
            {/* Bento hero row — featured "Most versatile" tile + a stacked pair. */}
            {featured && (
              <div
                style={{
                  display: 'grid',
                  gridTemplateColumns: '1.35fr 1fr',
                  gap: 12,
                  marginTop: 10,
                }}
              >
                {renderTile(featured, {
                  h: 236,
                  badge: (
                    <span
                      className="inline-flex items-center"
                      style={{
                        height: 26,
                        padding: '0 10px',
                        gap: 5,
                        borderRadius: 999,
                        fontSize: 11,
                        fontWeight: 600,
                        fontFamily: 'var(--font-accent)',
                        background: 'rgba(75,226,214,0.16)',
                        color: 'var(--mint)',
                        border: '1px solid rgba(75,226,214,0.45)',
                      }}
                    >
                      <Spark size={10} />
                      Most versatile
                    </span>
                  ),
                })}
                <div className="flex flex-col" style={{ gap: 12 }}>
                  {bentoTop.map((it) => renderTile(it, { h: 112 }))}
                </div>
              </div>
            )}

            {/* Remaining pieces — 2-col grid. */}
            {bentoRest.length > 0 && (
              <div
                className="grid grid-cols-2"
                style={{ gap: 12, marginTop: featured ? 12 : 10 }}
              >
                {bentoRest.map((it) => renderTile(it))}
              </div>
            )}
          </>
        )}
      </div>

      {/* Floating Action Button — teal gradient, opens the AddItemDrawer. A small
          "Scan a tag" glass pill sits beside it as the honest entry to the C6
          roadmap scan screen (the drawer's 3 sources are owned elsewhere). */}
      <div className="pointer-events-none fixed bottom-[104px] left-0 right-0 z-40 mx-auto flex max-w-[430px] items-center justify-end gap-3 px-6">
        <button
          type="button"
          onClick={() => router.push('/scan')}
          className="pointer-events-auto flex items-center gap-2 rounded-full text-white transition-transform active:scale-95"
          style={{
            height: 40,
            padding: '0 15px',
            fontSize: 13,
            fontWeight: 600,
            background: 'rgba(255,255,255,0.09)',
            border: '1px solid rgba(255,255,255,0.15)',
            backdropFilter: 'blur(10px)',
            WebkitBackdropFilter: 'blur(10px)',
          }}
        >
          <ScanLine size={16} />
          Scan a tag
        </button>
        <button
          type="button"
          aria-label="Add to closet"
          onClick={() => setDrawerOpen(true)}
          className="pointer-events-auto flex items-center justify-center rounded-full text-white transition-transform hover:scale-105 active:scale-95"
          style={{
            width: 56,
            height: 56,
            background: 'var(--grad-teal)',
            boxShadow: '0 10px 24px rgba(0,0,0,0.4)',
          }}
        >
          <Plus size={26} strokeWidth={2.6} />
        </button>
      </div>

      <AddItemDrawer
        open={drawerOpen}
        onOpenChange={setDrawerOpen}
        onGmailClick={() => {
          setDrawerOpen(false);
          router.push('/review');
        }}
      />

      <BottomNavBar activeRoute={pathname} />
    </AppShell>
  );
}
