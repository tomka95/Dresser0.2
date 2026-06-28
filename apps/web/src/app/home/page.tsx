'use client';

import React, { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { Cloud } from 'lucide-react';

import { useRequireAuth } from '@/lib/auth/useRequireAuth';
import { getCurrentUser } from '@/lib/api/auth';
import { useClosetStore } from '@/stores/useClosetStore';
import { AppShell } from '@/components/layout/AppShell';
import { BottomNavBar } from '@/components/layout/BottomNavBar';
import { GlassCard } from '@/components/ui/GlassCard';
import { Spark } from '@/components/ui/Spark';
import { SectionHeader } from '@/components/ui/SectionHeader';
import { ItemTile } from '@/components/closet/ItemTile';

export default function HomePage() {
  const router = useRouter();
  const { session, status } = useRequireAuth();
  const isAuth = status === 'authenticated';

  const [firstName, setFirstName] = useState('there');

  const items = useClosetStore((s) => s.items);
  const isLoading = useClosetStore((s) => s.isLoading);
  const fetchItems = useClosetStore((s) => s.fetchItems);
  const hasFetchedItems = useClosetStore((s) => s.hasFetchedItems);

  useEffect(() => {
    if (!isAuth) return;
    if (!hasFetchedItems) fetchItems();

    let active = true;
    getCurrentUser()
      .then((u) => {
        if (!active) return;
        const name = u.display_name || u.full_name || '';
        const first = name.trim().split(/\s+/)[0];
        if (first) setFirstName(first);
      })
      .catch(() => {
        // Fall back to "there"; non-fatal.
      });
    return () => {
      active = false;
    };
  }, [isAuth, hasFetchedItems, fetchItems]);

  if (status === 'loading' || !isAuth) {
    return (
      <AppShell contentClassName="px-6 pt-12">
        <div className="h-10 w-40 rounded-xl bg-white/5 animate-pulse" />
      </AppShell>
    );
  }

  const firstFour = items.slice(0, 4);
  const showSkeletons = isLoading && items.length === 0;

  return (
    <AppShell contentClassName="px-6 pt-12 pb-[120px]">
      {/* Greeting */}
      <h1
        className="text-white m-0"
        style={{ fontSize: 34, fontWeight: 700, letterSpacing: '-0.5px' }}
      >
        Hey, {firstName}!
      </h1>
      <p className="m-0 mt-1.5 mb-[26px]" style={{ color: 'rgba(255,255,255,0.8)', fontSize: 17, fontWeight: 300 }}>
        Want to find your outfit for today?
      </p>

      {/* Weather + calendar / AI suggest cards */}
      <div className="flex flex-col gap-[14px] mb-[26px]">
        {/* TODO: not backed by API — weather + calendar are static placeholders */}
        <GlassCard tint="frost" padding={18}>
          <div className="flex items-center gap-4" style={{ minHeight: 84 }}>
            <div className="flex items-center gap-1.5">
              <Cloud size={26} className="text-white/90" />
              <span className="text-white font-bold leading-none" style={{ fontSize: 36 }}>
                21
              </span>
              <span className="text-white/80" style={{ fontSize: 16 }}>
                °C
              </span>
            </div>
            <div style={{ width: 1, alignSelf: 'stretch', background: 'var(--tr-20)' }} />
            <div className="min-w-0">
              <div style={{ color: 'rgba(255,255,255,0.7)', fontSize: 13 }}>10:00</div>
              <div className="text-white font-bold truncate" style={{ fontSize: 17 }}>
                Meeting with Guy
              </div>
            </div>
          </div>
        </GlassCard>

        {/* TODO: not backed by API — AI suggestion is a static placeholder */}
        <GlassCard tint="ai" padding={18}>
          <div className="flex items-center gap-[14px]">
            <Spark size={40} />
            <div className="min-w-0">
              <div style={{ color: 'rgba(255,255,255,0.9)', fontSize: 13 }}>AI Suggests</div>
              <div className="text-white font-bold" style={{ fontSize: 18 }}>
                Layered look + boots
              </div>
            </div>
          </div>
        </GlassCard>
      </div>

      <SectionHeader title="Your closet" action="See all" onAction={() => router.push('/closet')} />

      <div className="grid grid-cols-2 gap-[14px] mt-3.5">
        {showSkeletons &&
          Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="aspect-[3/4] rounded-2xl bg-white/5 animate-pulse" />
          ))}

        {!showSkeletons &&
          firstFour.map((item) => (
            <ItemTile
              key={item.id}
              item={{ id: item.id, name: item.name, brand: item.brand, imageUrl: item.imageUrl }}
              onClick={(id) => router.push(`/closet/${id}`)}
            />
          ))}
      </div>

      {!showSkeletons && items.length === 0 && (
        <button
          type="button"
          onClick={() => router.push('/closet')}
          className="mt-2 text-left"
          style={{ color: 'rgba(255,255,255,0.7)', fontSize: 14 }}
        >
          Your closet is empty — add your first piece.
        </button>
      )}

      <BottomNavBar active="home" />
    </AppShell>
  );
}
