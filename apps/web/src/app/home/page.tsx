'use client';

// Home — greeting, weather/calendar (mock), AI suggestion (mock), real closet grid.

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { RotateCw } from 'lucide-react';
import { useRequireAuth } from '@/lib/auth/useRequireAuth';
import { getCurrentUser } from '@/lib/api/auth';
import { useClosetStore } from '@/stores/useClosetStore';
import { AppShell } from '@/components/layout/AppShell';
import { BottomNavBar } from '@/components/layout/BottomNavBar';
import { GlassCard, ItemTile, SectionHeader, Spark } from '@/components/ds';
import type { ClosetItem } from '@tailor/contracts';

// Mock items shown only while the closet is empty (design preview parity).
const MOCK_ITEMS: ClosetItem[] = [
  {
    id: 'mock-1',
    userId: 'mock-user',
    name: 'Black Jeans',
    category: 'bottom',
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
    imageUrl: 'https://images.unsplash.com/photo-1541099649105-f69ad21f3246?q=80&w=300&auto=format&fit=crop',
    brand: "Levi's",
  },
  {
    id: 'mock-2',
    userId: 'mock-user',
    name: 'White T-Shirt',
    category: 'top',
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
    imageUrl: 'https://images.unsplash.com/photo-1521572163474-6864f9cf17ab?q=80&w=300&auto=format&fit=crop',
    brand: 'Uniqlo',
  },
  {
    id: 'mock-3',
    userId: 'mock-user',
    name: 'Leather Jacket',
    category: 'outerwear',
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
    imageUrl: 'https://images.unsplash.com/photo-1551028919-ac66e6a39b51?q=80&w=300&auto=format&fit=crop',
    brand: 'AllSaints',
  },
  {
    id: 'mock-4',
    userId: 'mock-user',
    name: 'Chelsea Boots',
    category: 'shoes',
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
    imageUrl: 'https://images.unsplash.com/photo-1638247025967-b4e38f787b76?q=80&w=300&auto=format&fit=crop',
    brand: 'Common Projects',
  },
];

export default function HomePage() {
  const router = useRouter();
  // Gate on the Supabase session; redirects to /sign-in when absent.
  const { session, loading } = useRequireAuth();
  const isAuth = !!session;

  const items = useClosetStore((state) => state.items);
  const fetchItems = useClosetStore((state) => state.fetchItems);
  const hasFetchedItems = useClosetStore((state) => state.hasFetchedItems);

  const [firstName, setFirstName] = useState<string | null>(null);

  useEffect(() => {
    if (isAuth && !hasFetchedItems) {
      fetchItems();
    }
  }, [isAuth, hasFetchedItems, fetchItems]);

  // Greeting name: backend profile first, session metadata as fallback.
  useEffect(() => {
    if (!isAuth) return;
    let active = true;
    getCurrentUser()
      .then((u) => {
        if (!active) return;
        const name = u.display_name || u.full_name;
        if (name) setFirstName(name.trim().split(/\s+/)[0]);
      })
      .catch(() => {
        const meta = (session?.user?.user_metadata ?? {}) as { full_name?: string };
        if (active && meta.full_name) setFirstName(meta.full_name.trim().split(/\s+/)[0]);
      });
    return () => {
      active = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isAuth]);

  if (loading || !isAuth) {
    return null;
  }

  // Real items when present; mock preview only for an empty closet.
  const displayItems = (items.length > 0 ? items : MOCK_ITEMS).slice(0, 4);

  return (
    <AppShell>
      <div style={{ padding: '52px 24px 120px' }}>
        <h1 className="m-0 text-[34px] font-bold tracking-[-0.5px] text-white">
          Hey, {firstName ?? 'there'}!
        </h1>
        <p className="mb-[22px] mt-1.5 text-[17px] font-light text-white/80">
          Want to find your outfit for today?
        </p>

        <div className="mb-[26px] flex flex-col gap-3.5">
          {/* Weather + next calendar event — MOCK data (no backend contract yet). */}
          <GlassCard tint="frost" padding={18} className="flex min-h-[84px] items-center">
            <div className="flex items-center gap-2.5 pr-4">
              <RotateCw size={26} aria-hidden />
              <div className="flex items-start">
                <span className="text-[36px] font-bold leading-none">21</span>
                <span className="mt-0.5 text-[16px]">°C</span>
              </div>
            </div>
            <div className="mx-4 h-[38px] w-px" style={{ background: 'var(--tr-20)' }} aria-hidden />
            <div>
              <div className="text-[13px] opacity-90">10:00</div>
              <div className="text-[17px] font-bold">Meeting with Guy</div>
            </div>
          </GlassCard>

          {/* AI suggestion — MOCK copy; tapping opens the outfits screen. */}
          <GlassCard
            tint="ai"
            padding={18}
            className="flex min-h-[84px] cursor-pointer items-center gap-3.5"
            onClick={() => router.push('/outfits')}
            role="button"
          >
            <Spark />
            <div>
              <div className="text-[13px] font-medium opacity-90">AI Suggests</div>
              <div className="text-[18px] font-bold">Layered look + boots</div>
            </div>
          </GlassCard>
        </div>

        <SectionHeader dark title="Your closet" action="See all" onAction={() => router.push('/closet')} />
        <div className="mt-4 grid grid-cols-2 gap-3.5">
          {displayItems.map((it) => (
            <ItemTile
              key={it.id}
              name={it.name}
              brand={it.brand}
              imageUrl={it.imageUrl}
              onClick={
                it.id.startsWith('mock-') ? () => router.push('/closet') : () => router.push(`/closet/${it.id}`)
              }
            />
          ))}
        </div>
      </div>

      <BottomNavBar activeRoute="/home" />
    </AppShell>
  );
}
