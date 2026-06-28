'use client';

import React, { useEffect, useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import { Plus, Shirt } from 'lucide-react';

import { useRequireAuth } from '@/lib/auth/useRequireAuth';
import { useClosetStore } from '@/stores/useClosetStore';
import { AppShell } from '@/components/layout/AppShell';
import { BottomNavBar } from '@/components/layout/BottomNavBar';
import { SearchBarDark } from '@/components/ui/SearchBarDark';
import { CategoryChips } from '@/components/ui/CategoryChips';
import { EmptyState } from '@/components/ui/EmptyState';
import { ItemTile } from '@/components/closet/ItemTile';
import { AddItemDrawer } from '@/components/closet/AddItemDrawer';
import { ConnectGmailModal, type ConnectGmailStatus } from '@/components/auth/ConnectGmailModal';
import { startGmailConnect } from '@/lib/api/gmail';

const CATEGORIES = [
  { id: 'all', label: 'All' },
  { id: 'top', label: 'Tops' },
  { id: 'bottom', label: 'Bottoms' },
  { id: 'outerwear', label: 'Outerwear' },
  { id: 'shoes', label: 'Shoes' },
];

export default function ClosetPage() {
  const router = useRouter();
  const { status } = useRequireAuth();
  const isAuth = status === 'authenticated';

  const [query, setQuery] = useState('');
  const [category, setCategory] = useState('all');
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [gmailOpen, setGmailOpen] = useState(false);
  const [gmailStatus, setGmailStatus] = useState<ConnectGmailStatus>('disconnected');
  // Favourites are client-only — not persisted to the backend.
  const [faved, setFaved] = useState<Set<string>>(new Set());

  const items = useClosetStore((s) => s.items);
  const isLoading = useClosetStore((s) => s.isLoading);
  const fetchItems = useClosetStore((s) => s.fetchItems);
  const hasFetchedItems = useClosetStore((s) => s.hasFetchedItems);
  const error = useClosetStore((s) => s.error);

  useEffect(() => {
    if (isAuth && !hasFetchedItems) fetchItems();
  }, [isAuth, hasFetchedItems, fetchItems]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return items.filter((item) => {
      const matchesCategory = category === 'all' || item.category === category;
      const matchesQuery =
        !q ||
        item.name.toLowerCase().includes(q) ||
        (item.brand?.toLowerCase().includes(q) ?? false);
      return matchesCategory && matchesQuery;
    });
  }, [items, category, query]);

  const toggleFav = (id: string) => {
    setFaved((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const handleGmailConnect = async () => {
    setGmailStatus('connecting');
    try {
      await startGmailConnect();
    } catch {
      setGmailStatus('error');
    }
  };

  if (status === 'loading' || !isAuth) {
    return (
      <AppShell contentClassName="px-6 pt-12">
        <div className="h-10 w-40 rounded-xl bg-white/5 animate-pulse" />
      </AppShell>
    );
  }

  const isEmpty = hasFetchedItems && !isLoading && items.length === 0;

  return (
    <AppShell contentClassName="px-6 pt-12 pb-[120px]">
      <h1 className="text-white m-0 mb-4" style={{ fontSize: 34, fontWeight: 700, letterSpacing: '-0.5px' }}>
        My Closet
      </h1>

      <SearchBarDark value={query} onChange={setQuery} placeholder="Search your closet" />

      <div className="mt-3 mb-4">
        <CategoryChips items={CATEGORIES} value={category} onChange={setCategory} />
      </div>

      {error && !isLoading ? (
        <div className="mt-14">
          <EmptyState
            icon={<Shirt size={40} />}
            title="Couldn’t load your closet"
            body={`Something went wrong talking to the server (${error}). Check you’re signed in and the backend is running, then retry.`}
            ctaLabel="Retry"
            onCta={() => fetchItems()}
          />
        </div>
      ) : isEmpty ? (
        <div className="mt-14">
          <EmptyState
            icon={<Shirt size={40} />}
            title="Your closet is empty"
            body="Add your first piece and Tailor starts building looks for you."
            ctaLabel="Add an item"
            ctaIcon={<Plus size={18} />}
            onCta={() => setDrawerOpen(true)}
          />
        </div>
      ) : (
        <div className="grid grid-cols-2 gap-[14px]">
          {isLoading && items.length === 0
            ? Array.from({ length: 4 }).map((_, i) => (
                <div key={i} className="aspect-[3/4] rounded-2xl bg-white/5 animate-pulse" />
              ))
            : filtered.map((item) => (
                <ItemTile
                  key={item.id}
                  item={{ id: item.id, name: item.name, brand: item.brand, imageUrl: item.imageUrl }}
                  faved={faved.has(item.id)}
                  onFav={toggleFav}
                  onClick={(id) => router.push(`/closet/${id}`)}
                />
              ))}
        </div>
      )}

      {/* FAB — pinned to the 430px app column (not the viewport edge) */}
      <div className="fixed bottom-[104px] left-1/2 -translate-x-1/2 w-full max-w-[430px] z-[60] pointer-events-none">
        <button
          type="button"
          onClick={() => setDrawerOpen(true)}
          aria-label="Add item"
          className="absolute right-6 flex items-center justify-center shadow-lg transition-transform active:scale-95 pointer-events-auto"
          style={{
            width: 56,
            height: 56,
            borderRadius: '50%',
            background: 'var(--grad-teal)',
          }}
        >
          <Plus size={26} className="text-white" />
        </button>
      </div>

      <AddItemDrawer
        open={drawerOpen}
        onOpenChange={setDrawerOpen}
        onGmailClick={() => {
          setGmailStatus('disconnected');
          setGmailOpen(true);
        }}
      />

      <ConnectGmailModal
        open={gmailOpen}
        status={gmailStatus}
        onClose={() => setGmailOpen(false)}
        onConnect={handleGmailConnect}
        onRetry={handleGmailConnect}
        onMaybeLater={() => setGmailOpen(false)}
      />

      <BottomNavBar active="closet" />
    </AppShell>
  );
}
