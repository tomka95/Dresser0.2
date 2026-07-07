'use client';

/**
 * /settings — grouped settings (Account / Connected accounts / Preferences /
 * Log out), restyled to the redesign surface system.
 *
 * WIRED (real):
 *   - identity row (GET /auth/me, Supabase session fallback)
 *   - Gmail connection status + connect (startGmailConnect full-page OAuth)
 *   - Log out (signOut → /sign-in), confirmed via a DialogFrame
 *
 * HONEST-DISABLED:
 *   - Gmail switch can only turn ON. Disconnect has no backend endpoint, so
 *     toggling OFF shows a "coming soon" hint instead of faking a disconnect.
 *
 * DEVICE-ONLY (labeled, persisted to localStorage — no preferences backend):
 *   - Sync frequency, Units, Notifications toggle.
 */

import React, { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import {
  Bell,
  BookOpen,
  ChevronRight,
  Link2,
  Lock,
  LogOut,
  Palette,
  PersonStanding,
  Ruler,
  RotateCw,
  SlidersHorizontal,
  Trash2,
  Wallet,
} from 'lucide-react';
import { useRequireAuth } from '@/lib/auth/useRequireAuth';
import { signOut } from '@/lib/auth';
import { getCurrentUser } from '@/lib/api/auth';
import { fetchGmailConnectionStatus, startGmailConnect } from '@/lib/api/gmail';
import { AppShell } from '@/components/layout/AppShell';
import {
  Btn,
  DialogFrame,
  DSAvatar,
  DSSwitch,
  GmailGlyph,
  M,
  RadioRow,
  Sheet,
  TopBar,
} from '@/components/ds';

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
  sub?: string;
  value?: string;
  control?: React.ReactNode;
  first?: boolean;
  danger?: boolean;
  /** Small pill after the label (e.g. "Preview" for roadmap screens). */
  badge?: string;
  onClick?: () => void;
}

function Row({ icon, label, sub, value, control, first, danger, badge, onClick }: RowProps) {
  const inner = (
    <>
      <span
        className="flex shrink-0 items-center justify-center rounded-xl"
        style={{
          width: 36,
          height: 36,
          background: danger ? 'rgba(251,44,54,0.11)' : 'rgba(255,255,255,0.08)',
          border: '1px solid rgba(255,255,255,0.09)',
          color: danger ? '#ff8087' : M.soft,
        }}
      >
        {icon}
      </span>
      <span className="min-w-0 flex-1">
        <span className="flex items-center gap-2">
          <span
            className="block text-[14.5px] font-medium"
            style={{ color: danger ? '#ff8087' : '#fff', letterSpacing: '-0.1px' }}
          >
            {label}
          </span>
          {badge && (
            <span
              className="rounded-full text-[10px] font-semibold uppercase"
              style={{
                padding: '2px 7px',
                letterSpacing: '0.06em',
                color: 'rgba(255,255,255,0.55)',
                background: 'rgba(255,255,255,0.08)',
                border: '1px solid rgba(255,255,255,0.12)',
              }}
            >
              {badge}
            </span>
          )}
        </span>
        {sub && <span className="mt-0.5 block text-[12px] leading-snug text-white/[0.55]">{sub}</span>}
      </span>
      {value && <span className="text-[13px] text-white/50">{value}</span>}
      {control ?? (onClick && <ChevronRight size={18} className="text-white/[0.36]" />)}
    </>
  );
  const style = { borderTop: first ? 'none' : '1px solid var(--tr-10)' } as React.CSSProperties;
  if (onClick) {
    return (
      <button type="button" onClick={onClick} className="flex w-full items-center gap-3.5 py-3.5 text-left" style={style}>
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

function Group({ title, children }: { title?: string; children: React.ReactNode }) {
  return (
    <div style={{ ...M.glass(24), padding: '4px 16px' }}>
      {title && (
        <div
          className="text-[11px] font-semibold uppercase"
          style={{ padding: '13px 2px 2px', letterSpacing: '0.13em', color: 'rgba(255,255,255,0.36)' }}
        >
          {title}
        </div>
      )}
      {children}
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
  const [gmailHint, setGmailHint] = useState<string | null>(null);

  const [syncFreq, setSyncFreq] = useState<string>('daily');
  const [measurement, setMeasurement] = useState<string>('metric');
  const [sizeSystem, setSizeSystem] = useState<string>('EU');

  const [syncPickerOpen, setSyncPickerOpen] = useState(false);
  const [unitsPickerOpen, setUnitsPickerOpen] = useState(false);
  const [logoutOpen, setLogoutOpen] = useState(false);
  const [loggingOut, setLoggingOut] = useState(false);

  // Hydrate local prefs after mount (SSR-safe).
  useEffect(() => {
    setSyncFreq(readPref('syncFreq', 'daily'));
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
    setLoggingOut(true);
    await signOut();
    router.push('/sign-in');
  };

  const syncLabel = SYNC_OPTIONS.find((o) => o.id === syncFreq)?.label ?? 'Daily';
  const unitsLabel = measurement === 'metric' ? 'Metric' : 'Imperial';

  return (
    <AppShell>
      <div style={{ padding: '62px 20px 60px' }}>
        <TopBar title="Settings" onBack={() => router.push('/profile')} />
        <div className="h-4" />

        <div className="flex flex-col" style={{ gap: 12 }}>
          <Group title="Account">
            <Row
              first
              icon={<DSAvatar name={name || email} size={22} />}
              label={name || 'Your account'}
              sub={email}
              onClick={() => router.push('/profile/edit')}
            />
            <Row icon={<Lock size={16} />} label="Change password" onClick={() => router.push('/settings/password')} />
            <Row
              icon={<Bell size={16} />}
              label="Notifications"
              sub="Daily look, finds, price drops"
              onClick={() => router.push('/settings/notifications')}
            />
            <Row
              icon={<Trash2 size={16} />}
              label="Delete account"
              danger
              onClick={() => router.push('/settings/account')}
            />
          </Group>

          <Group title="Connected accounts">
            <Row
              first
              icon={<GmailGlyph size={16} />}
              label="Gmail"
              sub={gmailConnected == null ? undefined : gmailConnected ? 'Connected · receipts only' : 'Not connected'}
              control={
                <DSSwitch
                  checked={!!gmailConnected}
                  aria-label="Gmail connection"
                  onChange={(next) => {
                    // Real connect: full-page OAuth redirect. Disconnect has no
                    // endpoint yet, so turning OFF only surfaces an honest hint.
                    if (next && !gmailConnected) {
                      setGmailHint(null);
                      startGmailConnect().catch(() => undefined);
                    } else if (!next && gmailConnected) {
                      setGmailHint(
                        'Disconnect is coming soon — for now, remove Tailor from your Google account permissions.',
                      );
                    }
                  }}
                />
              }
            />
            {gmailHint && (
              <div className="pb-3 text-[12px] leading-snug text-white/[0.55]">{gmailHint}</div>
            )}
            <Row
              icon={<RotateCw size={16} />}
              label="Sync frequency"
              value={syncLabel}
              onClick={() => setSyncPickerOpen(true)}
            />
            <Row
              icon={<Link2 size={16} />}
              label="More connectors"
              sub="Outlook, Amazon, Photos — coming"
              onClick={() => router.push('/settings/connectors')}
            />
          </Group>

          <Group title="Styling">
            <Row
              first
              icon={<SlidersHorizontal size={16} />}
              label="My style profile"
              onClick={() => router.push('/settings/style')}
            />
            <Row icon={<Ruler size={16} />} label="Sizes & fit" onClick={() => router.push('/settings/sizes')} />
            <Row
              icon={<Wallet size={16} />}
              label="Budget bands"
              sub="Set what's comfortable"
              onClick={() => router.push('/settings/budget')}
            />
            <Row
              icon={<PersonStanding size={16} />}
              label="Body shape"
              sub="Optional — for fit advice"
              badge="Preview"
              onClick={() => router.push('/settings/body')}
            />
            <Row
              icon={<Palette size={16} />}
              label="Color analysis"
              sub="Find your season"
              badge="Preview"
              onClick={() => router.push('/settings/color')}
            />
          </Group>

          <Group title="App">
            <Row
              first
              icon={<BookOpen size={16} />}
              label="Units"
              value={unitsLabel}
              onClick={() => setUnitsPickerOpen(true)}
            />
          </Group>

          <Group>
            <Row
              first
              icon={<LogOut size={16} />}
              label="Log out"
              onClick={() => setLogoutOpen(true)}
            />
          </Group>
        </div>

        <div className="mt-4 text-center text-[11.5px] text-white/[0.36]">
          Sync frequency, notifications and units are saved on this device only.
        </div>
        <div className="mt-2 text-center text-[12px] text-white/[0.36]">Tailor v2.0.0</div>
      </div>

      {/* Log out confirm (REAL signOut). */}
      <DialogFrame
        open={logoutOpen}
        onOpenChange={setLogoutOpen}
        iconTone="plain"
        icon={<LogOut size={23} />}
        title="Log out?"
        sub="Your closet stays synced to your account — nothing is deleted."
      >
        <div className="mt-5 flex flex-col" style={{ gap: 9 }}>
          <Btn fullWidth size="md" pending={loggingOut} onClick={handleLogout}>
            Log out
          </Btn>
          <Btn variant="ghost" fullWidth size="md" onClick={() => setLogoutOpen(false)}>
            Stay signed in
          </Btn>
        </div>
      </DialogFrame>

      {/* Sync frequency picker (DEVICE-ONLY — backend scheduling not built). */}
      <Sheet
        open={syncPickerOpen}
        onClose={() => setSyncPickerOpen(false)}
        title="Sync frequency"
        sub="Saved on this device — how often Tailor would scan Gmail"
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

      {/* Units picker (DEVICE-ONLY). */}
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
