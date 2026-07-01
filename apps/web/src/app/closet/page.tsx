'use client';

// STATUS: implements Closet screen matching Figma node 26-1122

import { useEffect, useState, useMemo } from 'react';
import { useRouter, usePathname } from 'next/navigation';
import { useRequireAuth } from '@/lib/auth/useRequireAuth';
import { BottomNavBar } from '@/components/layout/BottomNavBar';
import { useClosetStore } from '@/stores/useClosetStore';
import { ClosetHeader } from '@/components/closet/ClosetHeader';
import { ClosetSearchBar } from '@/components/closet/ClosetSearchBar';
import { CategoryFilters } from '@/components/closet/CategoryFilters';
import { ClosetGrid } from '@/components/closet/ClosetGrid';
import { AddItemDrawer } from '@/components/closet/AddItemDrawer';
import { Plus } from 'lucide-react';

export default function ClosetPage() {
  const router = useRouter();
  const pathname = usePathname();
  // Gate on the Supabase session; redirects to /sign-in when absent.
  const { session, loading: checkingAuth } = useRequireAuth();
  const isAuth = !!session;
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedCategory, setSelectedCategory] = useState('all');
  
  // Drawer state
  const [drawerOpen, setDrawerOpen] = useState(false);
  
  const items = useClosetStore((state) => state.items);
  const fetchItems = useClosetStore((state) => state.fetchItems);
  const hasFetchedItems = useClosetStore((state) => state.hasFetchedItems);
  const isLoading = useClosetStore((state) => state.isLoading);
  const error = useClosetStore((state) => state.error);

  useEffect(() => {
    // Fetch items if authenticated and not yet fetched
    if (isAuth && !hasFetchedItems) {
      fetchItems();
    }
  }, [isAuth, hasFetchedItems, fetchItems]);

  // Filter the REAL closet items by category and search. No mock fallback — an
  // empty result renders the empty state below, never placeholder cards.
  const filteredItems = useMemo(() => {
    let filtered = items;

    // Filter by category
    if (selectedCategory !== 'all') {
      filtered = filtered.filter((item) => item.category === selectedCategory);
    }

    // Filter by search query
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

  if (checkingAuth) {
    return null; // Or a loading spinner
  }

  if (!isAuth) {
    return null;
  }

  return (
    <div className="min-h-full bg-[#1E1E1E] relative pb-24">
      {/* Background Layers */}
      <div className="fixed top-0 bottom-0 left-0 right-0 z-0 w-full max-w-[430px] mx-auto pointer-events-none">
        {/* Layer 1: decorative closet backdrop over the --app-bg fallback */}
        <div
          className="absolute inset-0"
          style={{
            background: 'var(--app-bg)',
            backgroundImage: "url('/images/closet-background-blur.jpg')",
            backgroundSize: 'cover',
            backgroundPosition: 'center',
          }}
        />

        {/* Layer 2: Dark Gradient Overlay */}
        <div 
          className="absolute inset-0"
          style={{
            background: 'linear-gradient(180deg, rgba(0,0,0,0.8) 0%, rgba(0,0,0,0.6) 50%, rgba(0,0,0,0.9) 100%)'
          }}
        />
      </div>

      {/* Main Content */}
      <div className="relative z-10 px-6 pt-12">
        <ClosetHeader />
        <ClosetSearchBar value={searchQuery} onChange={setSearchQuery} />
        <CategoryFilters
          selectedCategory={selectedCategory}
          onSelectCategory={setSelectedCategory}
        />
        {/* First load: show a spinner rather than flashing the empty state before
            the /closet fetch resolves. On error, offer a retry. Otherwise hand the
            REAL items to the grid, which renders its own empty state when there are none. */}
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
            <p className="text-white/60 text-sm">Couldn&rsquo;t load your closet.</p>
            <button
              type="button"
              onClick={() => fetchItems()}
              className="mt-2 text-sm underline text-white/80"
            >
              Retry
            </button>
          </div>
        ) : (
          <ClosetGrid items={filteredItems} />
        )}
      </div>

      {/* Floating Action Button */}
      <div className="fixed bottom-20 left-0 right-0 z-40 max-w-[430px] mx-auto px-6 pointer-events-none flex justify-end">
        <button
          onClick={() => setDrawerOpen(true)}
          className="w-14 h-14 rounded-full bg-white flex items-center justify-center shadow-lg transition-transform hover:scale-105 active:scale-95 pointer-events-auto"
        >
          <Plus className="w-7 h-7 text-[rgb(10,54,51)]" strokeWidth={3} />
        </button>
      </div>

      {/* Add Item Drawer (Bottom Sheet) */}
      <AddItemDrawer 
        open={drawerOpen} 
        onOpenChange={setDrawerOpen}
        onGmailClick={() => {
          setDrawerOpen(false);
          router.push('/review');
        }}
        onPhotoClick={() => {
          setDrawerOpen(false);
          router.push('/add-photo');
        }}
      />

      <BottomNavBar activeRoute={pathname} />
    </div>
  );
}
