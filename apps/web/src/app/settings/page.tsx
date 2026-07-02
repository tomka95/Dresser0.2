'use client';

/**
 * /settings — grouped settings (design: Account / Connected accounts / Preferences
 * / Log out). REAL: identity row, Gmail connection status, log out. LOCAL-ONLY
 * (persisted to localStorage, no backend endpoints yet): sync frequency,
 * notifications, units.
 */

import React, { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { Bell, BookOpen, ChevronRight, Lock, Ruler, RotateCw, SlidersHorizontal } from 'lucide-react';
import { useRequireAuth } from '@/lib/auth/useRequireAuth';
import { signOut } from '@/lib/auth';
import { getCurrentUser } from '@/lib/api/auth';
import { fetchGmailConnectionStatus, startGmailConnect } from '@/lib/api/gmail';
import { AppShell } from '@/components/layout/AppShell';
import { DSAvatar, DSSwitch, GlassCard, GmailGlyph, RadioRow, Sheet, TopBar } from '@/components/ds';

const SYNC_OPTIONS = [
  { id: 'realtime', label: 'Real-time', sub: 'As receipts arrive' },
  { id: 'hourly', label: 'Hourly' },
  { id: 'daily', label: 'Daily', sub: 'Recommended' },
  { id: 'weekly', label: 'Weekly' },
  { id: 'manual', label: 'Manual only', sub: 'You trigger each sync' },
] as const;

const MEASUREMENTS = [
  { id: 'metric', label: 'Metric', sub: 'cm · kg' },
  { id: 'imperial', label: 'Imperial', sub: 'in · lb' },
] as const;

const SIZE_SYSTEMS = ['EU', 'US', 'UK'] as const;

function readPref<T>(key: string, fallback: T): T {
  if (typeof window === 'undefined') return fallback;
  try {
    const raw = window.localStorage.getItem(`tailor.pref.${key}`);
    return raw ? (JSON.parse(raw) as T) : fallback;
  } catch {
    return fallback;
  }
}

function writePref<T>(key: string, value: T) {
  try {
    window.localStorage.setItem(`tailor.pref.${key}`, JSON.stringify(value));
  } catch {
    /* storage unavailable — keep in-memory only */
  }
}

interface RowProps {
  icon: React.ReactNode;
  label: string;
  value?: string;
  control?: React.ReactNode;
  first?: boolean;
  onClick?: () => void;
}

function Row({ icon, label, value, control, first, onClick }: RowProps) {
  const inner = (
    <>
      <span
        className="flex shrink-0 items-center justify-center rounded-[9px] text-white"
        style={{ width: 36, height: 36, background: 'var(--tr-10)' }}
      >
        {icon}
      </span>
      <span className="flex-1 text-left text-[15px] text-white">{label}</span>
      {value && <span className="text-[13px] text-white/50">{value}</span>}
      {control ?? <ChevronRight size={18} className="text-white/60" />}
    </>
  );
  const style = { borderTop: first ? 'none' : '1px solid var(--tr-10)' };
  if (onClick) {
    return (
      <button type="button" onClick={onClick} className="flex w-full items-center gap-3.5 py-3.5" style={style}>
        {inner}
      </button>
    );
  }
  return (
    <div className="flex items-center gap-3.5 py-3.5" style={style}>
      {inner}
    </div>
  );
}

function Group({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="mb-[22px]">
      <div
        className="mx-1 mb-2.5 text-[12px] font-semibold uppercase tracking-[0.5px]"
        style={{ color: 'rgba(255,255,255,0.5)' }}
      >
        {title}
      </div>
      <GlassCard tint="scrim" padding={6}>
        <div className="px-3">{children}</div>
      </GlassCard>
    </div>
  );
}

export default function SettingsPage() {
  const router = useRouter();
  const { session, loading } = useRequireAuth();
  const isAuth = !!session;

  const [name, setName] = useState<string>('');
  const [email, setEmail] = useState<string>('');
  const [gmailConnected, setGmailConnected] = useState<boolean | null>(null);

  const [syncFreq, setSyncFreq] = useState<string>('daily');
  const [notifications, setNotifications] = useState(false);
  const [measurement, setMeasurement] = useState<string>('metric');
  const [sizeSystem, setSizeSystem] = useState<string>('EU');

  const [syncPickerOpen, setSyncPickerOpen] = useState(false);
  const [unitsPickerOpen, setUnitsPickerOpen] = useState(false);

  // Hydrate local prefs after mount (SSR-safe).
  useEffect(() => {
    setSyncFreq(readPref('syncFreq', 'daily'));
    setNotifications(readPref('notifications', false));
    setMeasurement(readPref('measurement', 'metric'));
    setSizeSystem(readPref('sizeSystem', 'EU'));
  }, []);

  useEffect(() => {
    if (!isAuth) return;
    let active = true;
    getCurrentUser()
      .then((u) => {
        if (!active) return;
        setName(u.display_name || u.full_name || '');
        setEmail(u.email);
      })
      .catch(() => {
        if (active && session?.user) {
          const meta = (session.user.user_metadata ?? {}) as { full_name?: string };
          setName(meta.full_name ?? '');
          setEmail(session.user.email ?? '');
        }
      });
    fetchGmailConnectionStatus()
      .then((s) => active && setGmailConnected(s.connected))
      .catch(() => active && setGmailConnected(null));
    return () => {
      active = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isAuth]);

  if (loading || !isAuth) return null;

  const handleLogout = async () => {
    await signOut();
    router.push('/sign-in');
  };

  const syncLabel = SYNC_OPTIONS.find((o) => o.id === syncFreq)?.label ?? 'Daily';
  const unitsLabel = measurement === 'metric' ? 'Metric' : 'Imperial';

  return (
    <AppShell>
      <div style={{ padding: '48px 24px 60px' }}>
        <div className="mb-2">
          <TopBar title="Settings" onBack={() => router.push('/profile')} />
        </div>
        <div className="h-3" />

        <Group title="Account">
          <Row
            first
            icon={<DSAvatar name={name || email} size={28} />}
            label={name || 'Your account'}
            value={email}
            onClick={() => router.push('/profile/edit')}
          />
          <Row icon={<Lock size={17} />} label="Password" onClick={() => router.push('/settings/password')} />
          <Row icon={<Ruler size={17} />} label="Sizes & fit" onClick={() => router.push('/settings/sizes')} />
        </Group>

        <Group title="Connected accounts">
          <Row
            first
            icon={<GmailGlyph size={17} />}
            label="Gmail"
            value={gmailConnected == null ? undefined : gmailConnected ? 'Connected' : 'Not connected'}
            control={
              <DSSwitch
                checked={!!gmailConnected}
                aria-label="Gmail connection"
                onChange={(next) => {
                  // Real connect: full-page OAuth redirect. Disconnect has no
                  // endpoint yet, so the switch can only turn ON.
                  if (next && !gmailConnected) startGmailConnect().catch(() => undefined);
                }}
              />
            }
          />
          <Row
            icon={<RotateCw size={17} />}
            label="Sync frequency"
            value={syncLabel}
            onClick={() => setSyncPickerOpen(true)}
          />
        </Group>

        <Group title="Preferences">
          <Row
            first
            icon={<SlidersHorizontal size={17} />}
            label="Style preferences"
            onClick={() => router.push('/settings/style')}
          />
          <Row
            icon={<Bell size={17} />}
            label="Notifications"
            control={
              <DSSwitch
                checked={notifications}
                aria-label="Notifications"
                onChange={(v) => {
                  setNotifications(v);
                  writePref('notifications', v);
                }}
              />
            }
          />
          <Row icon={<BookOpen size={17} />} label="Units" value={unitsLabel} onClick={() => setUnitsPickerOpen(true)} />
        </Group>

        <button
          type="button"
          onClick={handleLogout}
          className="h-[50px] w-full cursor-pointer rounded-full text-[15px] font-semibold"
          style={{
            border: '1px solid rgba(251,44,54,0.4)',
            background: 'rgba(251,44,54,0.12)',
            color: '#ff6b6b',
            fontFamily: 'var(--font-sans)',
          }}
        >
          Log out
        </button>
        <div className="mt-[18px] text-center text-[12px]" style={{ color: 'rgba(255,255,255,0.35)' }}>
          Tailor v2.0.0
        </div>
      </div>

      {/* Sync frequency picker (LOCAL preference — backend scheduling not built). */}
      <Sheet
        open={syncPickerOpen}
        onClose={() => setSyncPickerOpen(false)}
        title="Sync frequency"
        sub="How often Tailor scans Gmail for new receipts"
      >
        {SYNC_OPTIONS.map((o, i) => (
          <RadioRow
            key={o.id}
            first={i === 0}
            label={o.label}
            sub={'sub' in o ? o.sub : undefined}
            on={syncFreq === o.id}
            onSelect={() => {
              setSyncFreq(o.id);
              writePref('syncFreq', o.id);
              setSyncPickerOpen(false);
            }}
          />
        ))}
      </Sheet>

      {/* Units picker (LOCAL preference). */}
      <Sheet open={unitsPickerOpen} onClose={() => setUnitsPickerOpen(false)} title="Units" sub="Measurements and sizing system">
        <div
          className="mx-0.5 mb-0.5 mt-1 text-[11.5px] font-semibold uppercase tracking-[0.5px]"
          style={{ color: 'rgba(255,255,255,0.45)' }}
        >
          Measurement
        </div>
        {MEASUREMENTS.map((m, i) => (
          <RadioRow
            key={m.id}
            first={i === 0}
            label={m.label}
            sub={m.sub}
            on={measurement === m.id}
            onSelect={() => {
              setMeasurement(m.id);
              writePref('measurement', m.id);
            }}
          />
        ))}
        <div
          className="mx-0.5 mb-0.5 mt-4 text-[11.5px] font-semibold uppercase tracking-[0.5px]"
          style={{ color: 'rgba(255,255,255,0.45)' }}
        >
          Size system
        </div>
        {SIZE_SYSTEMS.map((s, i) => (
          <RadioRow
            key={s}
            first={i === 0}
            label={s}
            on={sizeSystem === s}
            onSelect={() => {
              setSizeSystem(s);
              writePref('sizeSystem', s);
            }}
          />
        ))}
      </Sheet>
    </AppShell>
  );
}
