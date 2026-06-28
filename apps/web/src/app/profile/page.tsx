'use client';

import React, { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { Bell, ChevronRight, Sliders } from 'lucide-react';

import { useRequireAuth } from '@/lib/auth/useRequireAuth';
import { getCurrentUser, type CurrentUserResponse } from '@/lib/api/auth';
import { useClosetStore } from '@/stores/useClosetStore';
import { useOutfitsStore } from '@/stores/useOutfitsStore';
import { AppShell } from '@/components/layout/AppShell';
import { BottomNavBar } from '@/components/layout/BottomNavBar';
import { Avatar } from '@/components/ui/Avatar';
import { GlassCard } from '@/components/ui/GlassCard';
import { Switch } from '@/components/ui/Switch';
import { LightButton } from '@/components/ui/LightButton';
import { GmailConnectCard } from '@/components/profile/GmailConnectCard';

export default function ProfilePage() {
  const router = useRouter();
  const { session, status } = useRequireAuth();
  const isAuth = status === 'authenticated';

  const [user, setUser] = useState<CurrentUserResponse | null>(null);
  // Local, not persisted to backend.
  const [autoSync, setAutoSync] = useState(true); // TODO: not backed by API
  const [styleNotifs, setStyleNotifs] = useState(false); // TODO: not backed by API
  const [showComingSoon, setShowComingSoon] = useState(false); // TODO: profile edit not backed by API

  const items = useClosetStore((s) => s.items);
  const fetchItems = useClosetStore((s) => s.fetchItems);
  const hasFetchedItems = useClosetStore((s) => s.hasFetchedItems);

  // NOTE: outfits are a MOCK backend.
  const outfits = useOutfitsStore((s) => s.outfits); // TODO: not backed by API (mock)
  const fetchOutfits = useOutfitsStore((s) => s.fetchOutfits);

  useEffect(() => {
    if (!isAuth) return;
    if (!hasFetchedItems) fetchItems();
    fetchOutfits();

    let active = true;
    getCurrentUser()
      .then((u) => active && setUser(u))
      .catch(() => {
        // Fall back to the Supabase session profile on backend failure.
        if (!active || !session?.user) return;
        const meta = (session.user.user_metadata ?? {}) as { full_name?: string; avatar_url?: string };
        setUser({
          id: session.user.id,
          email: session.user.email ?? '',
          full_name: meta.full_name,
          display_name: meta.full_name,
          avatar_url: meta.avatar_url,
          gmail_sync_completed_at: null,
        });
      });
    return () => {
      active = false;
    };
  }, [isAuth, session, hasFetchedItems, fetchItems, fetchOutfits]);

  if (status === 'loading' || !isAuth) {
    return (
      <AppShell contentClassName="px-6 pt-12">
        <div className="h-24 w-24 mx-auto rounded-full bg-white/5 animate-pulse" />
      </AppShell>
    );
  }

  const name = user?.display_name || user?.full_name || user?.email || 'You';
  const email = user?.email ?? '';

  return (
    <AppShell contentClassName="px-6 pt-12 pb-[120px]">
      {/* Identity */}
      <div className="flex flex-col items-center text-center">
        <Avatar name={name} size={100} ring src={user?.avatar_url} />
        <h1 className="text-white m-0 mt-4" style={{ fontSize: 26, fontWeight: 700 }}>
          {name}
        </h1>
        {email && (
          <p className="m-0 mt-1" style={{ color: 'rgba(255,255,255,0.55)', fontSize: 15 }}>
            {email}
          </p>
        )}
      </div>

      {/* Stats */}
      <div className="flex items-center justify-center gap-6 my-6">
        <div className="text-center">
          <div className="text-white font-bold" style={{ fontSize: 22 }}>
            {items.length}
          </div>
          <div style={{ color: 'rgba(255,255,255,0.55)', fontSize: 13 }}>Items</div>
        </div>
        <div style={{ width: 1, height: 32, background: 'var(--tr-20)' }} />
        <div className="text-center">
          {/* TODO: not backed by API — outfits store is a mock backend */}
          <div className="text-white font-bold" style={{ fontSize: 22 }}>
            {outfits.length}
          </div>
          <div style={{ color: 'rgba(255,255,255,0.55)', fontSize: 13 }}>Outfits</div>
        </div>
      </div>

      <div className="mb-4">
        <GmailConnectCard />
      </div>

      {/* Settings rows */}
      <GlassCard tint="scrim" padding={6}>
        <SettingsRow
          icon={<Bell size={18} className="text-white/85" />}
          label="Auto-sync Gmail receipts"
          control={<Switch checked={autoSync} onCheckedChange={setAutoSync} aria-label="Auto-sync Gmail receipts" />}
        />
        <Hairline />
        <SettingsRow
          icon={<Bell size={18} className="text-white/85" />}
          label="Style notifications"
          control={<Switch checked={styleNotifs} onCheckedChange={setStyleNotifs} aria-label="Style notifications" />}
        />
        <Hairline />
        <SettingsRow
          icon={<Sliders size={18} className="text-white/85" />}
          label="Settings"
          onClick={() => router.push('/settings')}
          control={<ChevronRight size={20} className="text-white/55" />}
        />
      </GlassCard>

      {/* Edit profile — no endpoint exists; shows a "Coming soon" note. */}
      {/* TODO: not backed by API — profile editing has no endpoint */}
      <div className="mt-5">
        <LightButton fullWidth onClick={() => setShowComingSoon(true)}>
          Edit profile
        </LightButton>
        {showComingSoon && (
          <p className="text-center mt-2" style={{ color: 'rgba(255,255,255,0.6)', fontSize: 13 }}>
            Coming soon
          </p>
        )}
      </div>

      <BottomNavBar active="profile" />
    </AppShell>
  );
}

function Hairline() {
  return <div style={{ height: 1, background: 'var(--tr-10)', margin: '0 14px' }} />;
}

interface SettingsRowProps {
  icon: React.ReactNode;
  label: string;
  control: React.ReactNode;
  onClick?: () => void;
}

function SettingsRow({ icon, label, control, onClick }: SettingsRowProps) {
  const content = (
    <>
      <span
        className="flex items-center justify-center shrink-0"
        style={{ width: 38, height: 38, borderRadius: 12, background: 'var(--tr-10)' }}
      >
        {icon}
      </span>
      <span className="flex-1 text-white" style={{ fontSize: 15 }}>
        {label}
      </span>
      {control}
    </>
  );

  if (onClick) {
    return (
      <button type="button" onClick={onClick} className="flex items-center gap-3 w-full text-left" style={{ padding: 14 }}>
        {content}
      </button>
    );
  }
  return (
    <div className="flex items-center gap-3" style={{ padding: 14 }}>
      {content}
    </div>
  );
}
