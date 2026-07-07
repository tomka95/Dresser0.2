'use client';

// Closet grid (§3 · C1) — real /closet items: search + category chips + 2-col
// tile grid with favourite hearts + FAB (opens AddItemDrawer). States: populated,
// empty, loading (skeleton — no blank gate), error (retry), filtered-no-match.

import { useEffect, useState, useMemo } from 'react';
import { useRouter, usePathname } from 'next/navigation';
import { Plus, X } from 'lucide-react';
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

  if (checkingAuth || !isAuth) {
    return null;
  }

  const closetIsEmpty = hasFetchedItems && !isLoading && !error && items.length === 0;
  // First load with nothing yet: show the grid skeleton (no blank gate).
  const showLoadingSkeleton = !hasFetchedItems && isLoading;
  const totalCount = items.length;

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
          <div className="grid grid-cols-2" style={{ gap: 12, marginTop: 10 }}>
            {filteredItems.map((it) => {
              const faved = favOverride[it.id] ?? !!it.isFavorite;
              return (
                <ItemTile
                  key={it.id}
                  name={it.name}
                  brand={it.brand}
                  imageUrl={it.imageUrl}
                  faved={faved}
                  onFav={() => toggleFavorite(it.id, faved)}
                  onClick={() => {
                    logEvent({ eventType: 'item_view', itemId: it.id, source: 'closet_grid' });
                    router.push(`/closet/${it.id}`);
                  }}
                />
              );
            })}
          </div>
        )}
      </div>

      {/* Floating Action Button — teal gradient, opens the AddItemDrawer. */}
      <div className="pointer-events-none fixed bottom-[104px] left-0 right-0 z-40 mx-auto flex max-w-[430px] justify-end px-6">
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
