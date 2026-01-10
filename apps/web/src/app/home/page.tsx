'use client';

// STATUS: Home screen with greeting, weather/calendar, AI suggestions, and clothing grid

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { isAuthenticated } from '@/lib/auth/storage';
import { HomeHeader } from '@/components/home/HomeHeader';
import { WeatherCalendarCard } from '@/components/home/WeatherCalendarCard';
import { AISuggestionCard } from '@/components/home/AISuggestionCard';
import { ClothingGrid } from '@/components/home/ClothingGrid';
import { BottomNavBar } from '@/components/layout/BottomNavBar';
import { useClosetStore } from '@/stores/useClosetStore';
import type { ClosetItem } from '@tailor/contracts';

// Mock items for empty state/preview
const MOCK_ITEMS: ClosetItem[] = [
  {
    id: 'mock-1',
    userId: 'mock-user',
    name: 'Black Jeans',
    category: 'bottom',
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
    imageUrl: 'https://images.unsplash.com/photo-1541099649105-f69ad21f3246?q=80&w=300&auto=format&fit=crop',
    brand: "Levi's"
  },
  {
    id: 'mock-2',
    userId: 'mock-user',
    name: 'White T-Shirt',
    category: 'top',
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
    imageUrl: 'https://images.unsplash.com/photo-1521572163474-6864f9cf17ab?q=80&w=300&auto=format&fit=crop',
    brand: 'Uniqlo'
  },
  {
    id: 'mock-3',
    userId: 'mock-user',
    name: 'Leather Jacket',
    category: 'outerwear',
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
    imageUrl: 'https://images.unsplash.com/photo-1551028919-ac66e6a39b51?q=80&w=300&auto=format&fit=crop',
    brand: 'AllSaints'
  },
  {
    id: 'mock-4',
    userId: 'mock-user',
    name: 'Chelsea Boots',
    category: 'shoes',
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
    imageUrl: 'https://images.unsplash.com/photo-1638247025967-b4e38f787b76?q=80&w=300&auto=format&fit=crop',
    brand: 'Common Projects'
  }
];

export default function HomePage() {
  const router = useRouter();
  const [isAuth, setIsAuth] = useState(false);
  const [checkingAuth, setCheckingAuth] = useState(true);
  
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

  if (checkingAuth) {
    return null; // Or a loading spinner
  }

  if (!isAuth) {
    return null;
  }

  // Use real items if available, otherwise fallback to mock for design preview
  const displayItems = items.length > 0 ? items : MOCK_ITEMS;

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
        <HomeHeader />
        
        <div className="flex flex-col gap-4 mb-8">
          <WeatherCalendarCard />
          <AISuggestionCard />
        </div>

        <ClothingGrid items={displayItems} />
      </div>

      <BottomNavBar activeRoute="/home" />
    </div>
  );
}
