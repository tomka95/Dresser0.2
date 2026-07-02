'use client';

/**
 * /profile — avatar + stats + Gmail connection + settings rows.
 * REAL: user identity (/auth/me with session fallback), closet item count,
 * Gmail connection state. MOCK/local: outfit count (no outfits backend),
 * the two preference switches (no persistence endpoints yet).
 */

import React, { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { ChevronRight, RotateCw, Bell, Settings as SettingsIcon } from 'lucide-react';
import { useRequireAuth } from '@/lib/auth/useRequireAuth';
import { getCurrentUser, type CurrentUserResponse } from '@/lib/api/auth';
import { useClosetStore } from '@/stores/useClosetStore';
import { useOutfitsStore } from '@/stores/useOutfitsStore';
import { AppShell } from '@/components/layout/AppShell';
import { BottomNavBar } from '@/components/layout/BottomNavBar';
import { GmailConnectCard } from '@/components/profile/GmailConnectCard';
import { DSAvatar, DSButton, DSSwitch, GlassCard } from '@/components/ds';

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
        className="flex shrink-0 items-center justify-center rounded-[10px] text-white"
        style={{ width: 38, height: 38, background: 'var(--tr-10)' }}
      >
        {icon}
      </span>
      <span className="flex-1 text-left text-[15px] text-white">{label}</span>
      {control}
    </>
  );
  if (onClick) {
    return (
      <button type="button" onClick={onClick} className="flex w-full items-center gap-3.5 py-3.5">
        {content}
      </button>
    );
  }
  return <div className="flex items-center gap-3.5 py-3.5">{content}</div>;
}

export default function ProfilePage() {
  const router = useRouter();
  // Gate on the Supabase session (three-state: never redirects while loading).
  const { session, loading: authLoading } = useRequireAuth();
  const [user, setUser] = useState<CurrentUserResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  // Local-only preference toggles (no backend persistence yet).
  const [autoSync, setAutoSync] = useState(true);
  const [styleNotifications, setStyleNotifications] = useState(false);

  const items = useClosetStore((state) => state.items);
  const fetchItems = useClosetStore((state) => state.fetchItems);
  const hasFetchedItems = useClosetStore((state) => state.hasFetchedItems);
  const outfits = useOutfitsStore((state) => state.outfits);

  useEffect(() => {
    if (authLoading || !session) return;

    let active = true;
    const loadProfile = async () => {
      try {
        const userData = await getCurrentUser();
        if (active) setUser(userData);
        if (!hasFetchedItems) {
          fetchItems();
        }
      } catch (error) {
        // A backend failure is NOT a session failure — fall back to the Supabase
        // session profile and stay on the page.
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

  if (authLoading || !session) {
    return null;
  }

  const displayName = user?.display_name || user?.full_name || 'Your profile';

  return (
    <AppShell>
      <div style={{ padding: '52px 24px 120px' }}>
        {!isLoading && (
          <>
            {/* Identity */}
            <div className="mb-6 flex flex-col items-center">
              <div className="mb-3.5">
                <DSAvatar name={displayName} src={user?.avatar_url} size={100} ring />
              </div>
              <h1 className="m-0 text-[26px] font-bold text-white">{displayName}</h1>
              <p className="m-0 mt-1 text-sm text-white/[0.55]">{user?.email}</p>
            </div>

            {/* Stats — items REAL, outfits from the mock suggestions store */}
            <div className="mb-[22px] flex items-center justify-center">
              <div className="w-[110px] text-center">
                <div className="text-[28px] font-bold text-white">{items.length}</div>
                <div className="text-[13px] text-white/[0.55]">Items</div>
              </div>
              <div className="h-10 w-px" style={{ background: 'var(--tr-20)' }} aria-hidden />
              <div className="w-[110px] text-center">
                <div className="text-[28px] font-bold text-white">{outfits.length}</div>
                <div className="text-[13px] text-white/[0.55]">Outfits</div>
              </div>
            </div>

            {/* Gmail connection (REAL status) */}
            <div className="mb-3.5">
              <GmailConnectCard
                email={user?.email}
                lastSyncAt={user?.gmail_sync_completed_at}
                itemCount={items.length}
              />
            </div>

            {/* Settings rows */}
            <GlassCard tint="scrim" padding={6} className="mb-4">
              <div className="px-3">
                <SettingsRow
                  icon={<RotateCw size={18} />}
                  label="Auto-sync Gmail receipts"
                  control={<DSSwitch checked={autoSync} onChange={setAutoSync} aria-label="Auto-sync Gmail receipts" />}
                />
                <div className="h-px" style={{ background: 'var(--tr-10)' }} aria-hidden />
                <SettingsRow
                  icon={<Bell size={18} />}
                  label="Style notifications"
                  control={
                    <DSSwitch
                      checked={styleNotifications}
                      onChange={setStyleNotifications}
                      aria-label="Style notifications"
                    />
                  }
                />
                <div className="h-px" style={{ background: 'var(--tr-10)' }} aria-hidden />
                <SettingsRow
                  icon={<SettingsIcon size={18} />}
                  label="Settings"
                  control={<ChevronRight size={18} className="text-white/60" />}
                  onClick={() => router.push('/settings')}
                />
              </div>
            </GlassCard>

            <DSButton variant="light" fullWidth pill onClick={() => router.push('/profile/edit')}>
              Edit profile
            </DSButton>
          </>
        )}
      </div>

      <BottomNavBar activeRoute="/profile" />
    </AppShell>
  );
}
