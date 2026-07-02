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

  // Real closet items only — never fake preview garments.
  const displayItems = items.slice(0, 4);

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
        {displayItems.length > 0 ? (
          <div className="mt-4 grid grid-cols-2 gap-3.5">
            {displayItems.map((it) => (
              <ItemTile
                key={it.id}
                name={it.name}
                brand={it.brand}
                imageUrl={it.imageUrl}
                onClick={() => router.push(`/closet/${it.id}`)}
              />
            ))}
          </div>
        ) : hasFetchedItems ? (
          // Real empty state — no fake garments. Tap to start adding.
          <button
            type="button"
            onClick={() => router.push('/add-photo')}
            className="mt-4 flex w-full flex-col items-center gap-1.5 rounded-2xl px-6 py-9 text-center transition-transform active:scale-[0.98]"
            style={{ background: 'var(--tr-10)', border: '1px dashed var(--tr-20)' }}
          >
            <span style={{ fontSize: 30, color: 'var(--mint)' }}>✦</span>
            <span className="text-[15px] font-semibold text-white">Your closet is empty</span>
            <span className="text-[13px]" style={{ color: 'rgba(255,255,255,0.6)' }}>
              Add your first item from a photo
            </span>
          </button>
        ) : (
          // Loading (pre-fetch): quiet skeleton, never fake items.
          <div className="mt-4 grid grid-cols-2 gap-3.5" aria-hidden>
            {[0, 1, 2, 3].map((i) => (
              <div
                key={i}
                className="aspect-square animate-pulse rounded-2xl"
                style={{ background: 'var(--tr-10)' }}
              />
            ))}
          </div>
        )}
      </div>

      <BottomNavBar activeRoute="/home" />
    </AppShell>
  );
}
