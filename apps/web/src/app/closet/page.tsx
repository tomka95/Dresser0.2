'use client';

// STATUS: implements Closet screen matching Figma node 26-1122

import { useEffect, useState, useMemo } from 'react';
import { useRouter, usePathname } from 'next/navigation';
import { isAuthenticated } from '@/lib/auth/storage';
import { BottomNavBar } from '@/components/layout/BottomNavBar';
import { useClosetStore } from '@/stores/useClosetStore';
import { ClosetHeader } from '@/components/closet/ClosetHeader';
import { ClosetSearchBar } from '@/components/closet/ClosetSearchBar';
import { CategoryFilters } from '@/components/closet/CategoryFilters';
import { ClosetGrid } from '@/components/closet/ClosetGrid';
import { AddItemDrawer } from '@/components/closet/AddItemDrawer';
import { Plus } from 'lucide-react';
import type { ClosetItem } from '@tailor/contracts';

// Mock items for empty state/preview
const MOCK_ITEMS: ClosetItem[] = [
  {
    id: 'mock-1',
    userId: 'mock-user',
    name: 'Beige Cardigan',
    category: 'top',
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
    imageUrl: 'https://images.unsplash.com/photo-1521572163474-6864f9cf17ab?q=80&w=300&auto=format&fit=crop',
    brand: 'Uniqlo'
  },
  {
    id: 'mock-2',
    userId: 'mock-user',
    name: 'Dark Denim',
    category: 'bottom',
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
    imageUrl: 'https://images.unsplash.com/photo-1541099649105-f69ad21f3246?q=80&w=300&auto=format&fit=crop',
    brand: "Levi's"
  },
  {
    id: 'mock-3',
    userId: 'mock-user',
    name: 'White Sneakers',
    category: 'shoes',
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
    imageUrl: 'https://images.unsplash.com/photo-1638247025967-b4e38f787b76?q=80&w=300&auto=format&fit=crop',
    brand: 'Common Projects'
  },
  {
    id: 'mock-4',
    userId: 'mock-user',
    name: 'Winter Coat',
    category: 'outerwear',
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
    imageUrl: 'https://images.unsplash.com/photo-1551028919-ac66e6a39b51?q=80&w=300&auto=format&fit=crop',
    brand: 'AllSaints'
  }
];

export default function ClosetPage() {
  const router = useRouter();
  const pathname = usePathname();
  const [isAuth, setIsAuth] = useState(false);
  const [checkingAuth, setCheckingAuth] = useState(true);
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedCategory, setSelectedCategory] = useState('all');
  
  // Drawer state
  const [drawerOpen, setDrawerOpen] = useState(false);
  
  const items = useClosetStore((state) => state.items);
  const fetchItems = useClosetStore((state) => state.fetchItems);
  const hasFetchedItems = useClosetStore((state) => state.hasFetchedItems);

  useEffect(() => {
    // Check auth on mount
    const auth = isAuthenticated();
    if (!auth) {
      router.push('/sign-up');
    } else {
      setIsAuth(true);
    }
    setCheckingAuth(false);
  }, [router]);

  useEffect(() => {
    // Fetch items if authenticated and not yet fetched
    if (isAuth && !hasFetchedItems) {
      fetchItems();
    }
  }, [isAuth, hasFetchedItems, fetchItems]);

  // Filter items by category and search
  const filteredItems = useMemo(() => {
    let filtered = items.length > 0 ? items : MOCK_ITEMS;

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
        {/* Layer 1: Image */}
        <div 
          className="absolute inset-0"
          style={{
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
        <ClosetGrid items={filteredItems} />
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
          router.push('/gmail-sync');
        }}
      />

      <BottomNavBar activeRoute={pathname} />
    </div>
  );
}
