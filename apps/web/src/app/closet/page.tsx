'use client';

// Closet — real /closet items with search, category chips, item grid, FAB + drawer.

import { useEffect, useState, useMemo } from 'react';
import { useRouter, usePathname } from 'next/navigation';
import { Plus } from 'lucide-react';
import { useRequireAuth } from '@/lib/auth/useRequireAuth';
import { useClosetStore } from '@/stores/useClosetStore';
import { AppShell } from '@/components/layout/AppShell';
import { BottomNavBar } from '@/components/layout/BottomNavBar';
import { AddItemDrawer } from '@/components/closet/AddItemDrawer';
import {
  CategoryChips,
  DSButton,
  DSSearchBar,
  HangerImg,
  ItemTile,
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
  // Gate on the Supabase session; redirects to /sign-in when absent.
  const { session, loading: checkingAuth } = useRequireAuth();
  const isAuth = !!session;
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedCategory, setSelectedCategory] = useState('all');
  const [drawerOpen, setDrawerOpen] = useState(false);
  // Favorites are LOCAL-ONLY (no backend endpoint yet) — a visual affordance.
  const [faves, setFaves] = useState<Record<string, boolean>>({});

  const items = useClosetStore((state) => state.items);
  const fetchItems = useClosetStore((state) => state.fetchItems);
  const hasFetchedItems = useClosetStore((state) => state.hasFetchedItems);
  const isLoading = useClosetStore((state) => state.isLoading);
  const error = useClosetStore((state) => state.error);

  useEffect(() => {
    if (isAuth && !hasFetchedItems) {
      fetchItems();
    }
  }, [isAuth, hasFetchedItems, fetchItems]);

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

  return (
    <AppShell>
      <div style={{ padding: '52px 24px 120px' }}>
        <h1 className="m-0 mb-[18px] text-[34px] font-bold tracking-[-0.5px] text-white">My Closet</h1>
        <div className="mb-[18px]">
          <DSSearchBar dark placeholder="Search your closet" value={searchQuery} onChange={setSearchQuery} />
        </div>
        <div className="mb-5">
          <CategoryChips dark items={CATEGORIES} value={selectedCategory} onChange={setSelectedCategory} />
        </div>

        {/* First load: spinner instead of flashing the empty state. On error, retry. */}
        {!hasFetchedItems && isLoading ? (
          <div className="flex justify-center py-16">
            <div
              className="h-8 w-8 rounded-full"
              style={{
                border: '3px solid var(--tr-20)',
                borderTopColor: 'var(--mint)',
                animation: 'tailor-spin 0.8s linear infinite',
              }}
            />
          </div>
        ) : error ? (
          <div className="py-12 text-center">
            <p className="text-sm text-white/60">Couldn&rsquo;t load your closet.</p>
            <button type="button" onClick={() => fetchItems()} className="mt-2 text-sm text-white/80 underline">
              Retry
            </button>
          </div>
        ) : closetIsEmpty ? (
          // Empty closet — hanger mark + CTA (keeps the header and nav around it).
          <div className="flex flex-col items-center px-4 pb-6 pt-14 text-center">
            <HangerImg w={190} className="mb-4 opacity-90" />
            <h2 className="m-0 mb-2.5 text-[22px] font-bold tracking-[-0.3px] text-white">
              Your closet is empty
            </h2>
            <p className="mx-auto mb-6 max-w-[280px] text-[14.5px] leading-relaxed text-white/[0.65]">
              Add your first piece and Tailor starts building looks for you.
            </p>
            <DSButton
              variant="light"
              pill
              leftIcon={<Plus size={18} strokeWidth={2.6} />}
              style={{ height: 48, padding: '0 26px' }}
              onClick={() => setDrawerOpen(true)}
            >
              Add an item
            </DSButton>
          </div>
        ) : filteredItems.length === 0 ? (
          <div className="py-12 text-center">
            <p className="text-sm text-white/60">No matches in your closet.</p>
          </div>
        ) : (
          <div className="grid grid-cols-2 gap-3.5">
            {filteredItems.map((it) => (
              <ItemTile
                key={it.id}
                name={it.name}
                brand={it.brand}
                imageUrl={it.imageUrl}
                faved={!!faves[it.id]}
                onFav={() => setFaves((f) => ({ ...f, [it.id]: !f[it.id] }))}
                onClick={() => router.push(`/closet/${it.id}`)}
              />
            ))}
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
