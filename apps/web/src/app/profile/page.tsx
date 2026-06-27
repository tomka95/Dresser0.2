'use client';

import React, { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { isAuthenticated, signOut } from '@/lib/auth';
import { getCurrentUser, type CurrentUserResponse } from '@/lib/api/auth';
import { useClosetStore } from '@/stores/useClosetStore';
import { BottomNavBar } from '@/components/layout/BottomNavBar';
import { ProfileHeader } from '@/components/profile/ProfileHeader';
import { ProfileStats } from '@/components/profile/ProfileStats';
import { StylePreferencesCard } from '@/components/profile/StylePreferencesCard';
import { GeneralSettingsCard } from '@/components/profile/GeneralSettingsCard';

// TODO: Replace with real API endpoints once available
const MOCK_FAVORITE_STYLES = ['Casual', 'Professional', 'Sporty', 'Minimalist'];
const MOCK_COLOR_PREFERENCES = ['Neutrals', 'Bold', 'Pastels', 'Monochrome'];
const MOCK_OUTFITS_COUNT = 653;

export default function ProfilePage() {
  const router = useRouter();
  const [user, setUser] = useState<CurrentUserResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  // Connect to closet store for real item count
  const items = useClosetStore((state) => state.items);
  const fetchItems = useClosetStore((state) => state.fetchItems);
  const hasFetchedItems = useClosetStore((state) => state.hasFetchedItems);

  useEffect(() => {
    const checkAuth = async () => {
      if (!(await isAuthenticated())) {
        router.push('/sign-in');
        return;
      }

      try {
        const userData = await getCurrentUser();
        setUser(userData);
        
        // Fetch items if not already fetched to get the count
        if (!hasFetchedItems) {
          fetchItems();
        }
      } catch (error) {
        console.error('Failed to load profile:', error);
        // If auth fails (e.g. token expired), redirect
        router.push('/login'); 
      } finally {
        setIsLoading(false);
      }
    };

    checkAuth();
  }, [router, hasFetchedItems, fetchItems]);

  const handleLogout = async () => {
    await signOut();
    router.push('/sign-in');
  };

  // Use real count if available, otherwise mock for initial design fidelity if store is empty/loading
  
  return (
    <div className="min-h-full bg-[#1E1E1E] relative pb-24">
      {/* Background Layers - Matches Home/Closet page */}
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

        {/* Layer 2: Even Darker Gradient for readability */}
        <div 
          className="absolute inset-0"
          style={{
            background: 'linear-gradient(180deg, rgba(0,0,0,0.8) 0%, rgba(0,0,0,0.6) 50%, rgba(0,0,0,0.95) 100%)'
          }}
        />
      </div>

      {/* Main Content */}
      <div className="relative z-10 w-full max-w-[430px] mx-auto min-h-screen flex flex-col">
        {!isLoading && (
          <>
            <ProfileHeader user={user} />
            
            <ProfileStats 
              itemsCount={items.length} 
              outfitsCount={MOCK_OUTFITS_COUNT} 
            />
            
            <StylePreferencesCard 
              favoriteStyles={MOCK_FAVORITE_STYLES}
              colorPreferences={MOCK_COLOR_PREFERENCES}
            />

            <GeneralSettingsCard onLogout={handleLogout} />
          </>
        )}
      </div>

      <BottomNavBar activeRoute="/profile" />
    </div>
  );
}
