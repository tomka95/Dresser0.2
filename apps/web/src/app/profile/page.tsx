'use client';

/**
 * /profile — avatar + style chip + stats bento + Gmail connection + entry rows.
 *
 * WIRED (real):
 *   - identity (GET /auth/me, with Supabase session fallback on backend failure)
 *   - "Items" stat — real count from the closet store
 *   - Gmail connection state (via GmailConnectCard → GET /gmail/oauth/status)
 *   - Edit / My style profile / Sizes & fit / Settings navigation
 *
 * HONEST about being NOT fully wired:
 *   - "Outfits worn" stat comes from the MOCK suggestions store (no outfits
 *     backend). Label copy makes clear it is a suggestion count, not worn history.
 *
 * Dedupe note: the two profile toggles (Auto-sync, Style notifications) were
 * removed. Those preferences now live in a single source — /settings — so the
 * profile no longer keeps a divergent, unpersisted copy.
 */

import React, { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { Pencil, Ruler, Settings as SettingsIcon } from 'lucide-react';
import { useRequireAuth } from '@/lib/auth/useRequireAuth';
import { getCurrentUser, type CurrentUserResponse } from '@/lib/api/auth';
import { useClosetStore } from '@/stores/useClosetStore';
import { useOutfitsStore } from '@/stores/useOutfitsStore';
import { AppShell } from '@/components/layout/AppShell';
import { BottomNavBar } from '@/components/layout/BottomNavBar';
import { GmailConnectCard } from '@/components/profile/GmailConnectCard';
import { DSAvatar, ErrorState, M, RoundBtn, Spark, Sk, SkCircle } from '@/components/ds';

/* Local Row-style entry — the settings-style list rows on the profile card.
   Kept inline (not the DS Row) because these are buttons that navigate. */
function EntryRow({
  icon,
  title,
  sub,
  last,
  onClick,
}: {
  icon: React.ReactNode;
  title: string;
  sub?: string;
  last?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="flex w-full items-center gap-3.5 py-3.5 text-left"
      style={{ borderBottom: last ? 'none' : '1px solid var(--tr-10)' }}
    >
      <span
        className="flex shrink-0 items-center justify-center rounded-xl"
        style={{
          width: 36,
          height: 36,
          background: 'rgba(255,255,255,0.08)',
          border: '1px solid rgba(255,255,255,0.09)',
          color: M.soft,
        }}
      >
        {icon}
      </span>
      <span className="min-w-0 flex-1">
        <span className="block text-[14.5px] font-medium text-white">{title}</span>
        {sub && <span className="mt-0.5 block text-[12px] leading-snug text-white/[0.55]">{sub}</span>}
      </span>
      <span className="flex text-white/[0.36]" aria-hidden>
        <ChevronRight />
      </span>
    </button>
  );
}

function ChevronRight() {
  return (
    <svg width={17} height={17} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
      <path d="M9 18l6-6-6-6" />
    </svg>
  );
}

export default function ProfilePage() {
  const router = useRouter();
  // Gate on the Supabase session AND onboarding completion.
  const { session, loading: authLoading } = useRequireAuth('/sign-in', { requireOnboarded: true });
  const [user, setUser] = useState<CurrentUserResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);

  const items = useClosetStore((state) => state.items);
  const fetchItems = useClosetStore((state) => state.fetchItems);
  const hasFetchedItems = useClosetStore((state) => state.hasFetchedItems);
  const outfits = useOutfitsStore((state) => state.outfits);

  useEffect(() => {
    if (authLoading || !session) return;

    let active = true;
    const loadProfile = async () => {
      setLoadError(false);
      try {
        const userData = await getCurrentUser();
        if (active) setUser(userData);
        if (!hasFetchedItems) {
          fetchItems();
        }
      } catch (error) {
        // A backend failure is NOT a session failure — fall back to the Supabase
        // session profile and stay on the page, but surface the cached-shell banner.
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
          setLoadError(true);
        }
      } finally {
        if (active) setIsLoading(false);
      }
    };

    loadProfile();
    return () => {
      active = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [authLoading, session, hasFetchedItems, fetchItems]);

  const reload = () => {
    setIsLoading(true);
    // Re-run the effect by nudging closet fetch + refetching /auth/me.
    getCurrentUser()
      .then((u) => {
        setUser(u);
        setLoadError(false);
      })
      .catch(() => setLoadError(true))
      .finally(() => setIsLoading(false));
  };

  if (authLoading || !session) {
    return null;
  }

  const displayName = user?.display_name || user?.full_name || 'Your profile';

  return (
    <AppShell>
      <div style={{ padding: '68px 20px 132px' }}>
        {isLoading ? (
          /* Loading skeleton — mirrors the populated layout. */
          <>
            <div className="flex items-center" style={{ gap: 16 }}>
              <SkCircle d={76} />
              <div className="flex-1">
                <Sk w="56%" h={19} />
                <Sk w="42%" h={11} style={{ marginTop: 9 }} />
                <Sk w={110} h={22} r={999} style={{ marginTop: 10 }} />
              </div>
            </div>
            <div className="grid grid-cols-3" style={{ gap: 10, marginTop: 20 }}>
              {[0, 1, 2].map((i) => (
                <Sk key={i} h={64} r={20} />
              ))}
            </div>
            <Sk h={72} r={22} style={{ marginTop: 12 }} />
            <Sk h={180} r={24} style={{ marginTop: 12 }} />
          </>
        ) : (
          <>
            {/* Identity header */}
            <div className="flex items-center" style={{ gap: 16 }}>
              <DSAvatar name={displayName} src={user?.avatar_url} size={76} ring />
              <div className="min-w-0 flex-1">
                <div
                  className="overflow-hidden text-ellipsis whitespace-nowrap text-white"
                  style={{ fontSize: 23, fontWeight: 700, letterSpacing: '-0.5px' }}
                >
                  {displayName}
                </div>
                <div className="mt-0.5 truncate text-[13px] text-white/[0.55]">{user?.email}</div>
                <button
                  type="button"
                  onClick={() => router.push('/settings/style')}
                  className="mt-2 inline-flex items-center gap-1.5"
                  style={{
                    padding: '4px 11px',
                    borderRadius: 999,
                    background: 'rgba(75,226,214,0.1)',
                    border: '1px solid rgba(75,226,214,0.3)',
                    color: 'var(--mint)',
                    fontSize: 11.5,
                    fontWeight: 600,
                  }}
                >
                  <Spark size={11} /> My style profile
                </button>
              </div>
              <RoundBtn
                size={38}
                aria-label="Edit profile"
                onClick={() => router.push('/profile/edit')}
                icon={<Pencil size={16} />}
              />
            </div>

            {loadError && (
              <ErrorState
                compact
                title="Couldn't refresh"
                sub="Stats and sync status didn't load — showing what's cached."
                retryLabel="Retry"
                onRetry={reload}
              />
            )}

            {/* Stats bento — Items REAL, Outfits from the mock suggestions store. */}
            <div className="grid grid-cols-2" style={{ gap: 10, marginTop: loadError ? 8 : 20 }}>
              {[
                { n: String(items.length), l: 'items' },
                { n: String(outfits.length), l: 'outfit ideas' },
              ].map((s) => (
                <div
                  key={s.l}
                  className="text-center"
                  style={{ ...M.glass(20), padding: '13px 8px' }}
                >
                  <div className="text-white" style={{ fontSize: 20, fontWeight: 700, letterSpacing: '-0.4px' }}>
                    {s.n}
                  </div>
                  <div className="mt-0.5 text-[11px] text-white/[0.55]">{s.l}</div>
                </div>
              ))}
            </div>

            {/* Gmail connection (REAL status) */}
            <div style={{ marginTop: 12 }}>
              <GmailConnectCard
                email={user?.email}
                lastSyncAt={user?.gmail_sync_completed_at}
                itemCount={items.length}
              />
            </div>

            {/* Entry rows — navigation only (toggles live in /settings now). */}
            <div style={{ ...M.glass(24), padding: '4px 16px', marginTop: 12 }}>
              <EntryRow
                icon={<Spark size={14} />}
                title="My style profile"
                sub="What you've told Tailor — see and edit it"
                onClick={() => router.push('/settings/style')}
              />
              <EntryRow
                icon={<Ruler size={16} />}
                title="Sizes & fit"
                onClick={() => router.push('/settings/sizes')}
              />
              <EntryRow
                icon={<SettingsIcon size={16} />}
                title="Settings"
                last
                onClick={() => router.push('/settings')}
              />
            </div>
          </>
        )}
      </div>

      <BottomNavBar activeRoute="/profile" />
    </AppShell>
  );
}
