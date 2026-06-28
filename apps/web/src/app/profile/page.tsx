'use client';

import React, { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { signOut } from '@/lib/auth';
import { useRequireAuth } from '@/lib/auth/useRequireAuth';
import { getCurrentUser, type CurrentUserResponse } from '@/lib/api/auth';
import { useClosetStore } from '@/stores/useClosetStore';
import { BottomNavBar } from '@/components/layout/BottomNavBar';
import { ProfileHeader } from '@/components/profile/ProfileHeader';
import { ProfileStats } from '@/components/profile/ProfileStats';
import { StylePreferencesCard } from '@/components/profile/StylePreferencesCard';
import { GmailConnectCard } from '@/components/profile/GmailConnectCard';
import { GeneralSettingsCard } from '@/components/profile/GeneralSettingsCard';

// TODO: Replace with real API endpoints once available
const MOCK_FAVORITE_STYLES = ['Casual', 'Professional', 'Sporty', 'Minimalist'];
const MOCK_COLOR_PREFERENCES = ['Neutrals', 'Bold', 'Pastels', 'Monochrome'];
const MOCK_OUTFITS_COUNT = 653;

export default function ProfilePage() {
  const router = useRouter();
  // Gate on the Supabase session (three-state: never redirects while loading).
  const { session, loading: authLoading } = useRequireAuth();
  const [user, setUser] = useState<CurrentUserResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  // Connect to closet store for real item count
  const items = useClosetStore((state) => state.items);
  const fetchItems = useClosetStore((state) => state.fetchItems);
  const hasFetchedItems = useClosetStore((state) => state.hasFetchedItems);

  useEffect(() => {
    // Wait for the auth state to resolve; the guard handles the unauthenticated
    // redirect, so only load profile data once we have a session.
    if (authLoading || !session) return;

    let active = true;
    const loadProfile = async () => {
      try {
        const userData = await getCurrentUser();
        if (active) setUser(userData);

        // Fetch items if not already fetched to get the count
        if (!hasFetchedItems) {
          fetchItems();
        }
      } catch (error) {
        // A backend authorization/data failure is NOT a session failure. The
        // Supabase guard (useRequireAuth) owns redirects; here we keep the user on
        // the page and fall back to their Supabase session profile.
        console.error('Failed to load profile from backend; using session fallback:', error);
        if (active && session?.user) {
          const meta = (session.user.user_metadata ?? {}) as {
            full_name?: string;
            avatar_url?: string;
          };
          setUser({
            id: session.user.id,
            email: session.user.email ?? '',
            full_name: meta.full_name,
            display_name: meta.full_name,
            avatar_url: meta.avatar_url,
            gmail_sync_completed_at: null,
          });
        }
      } finally {
        if (active) setIsLoading(false);
      }
    };

    loadProfile();
    return () => {
      active = false;
    };
  }, [authLoading, session, hasFetchedItems, fetchItems]);

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

            <GmailConnectCard />

            <GeneralSettingsCard onLogout={handleLogout} />
          </>
        )}
      </div>

      <BottomNavBar activeRoute="/profile" />
    </div>
  );
}
