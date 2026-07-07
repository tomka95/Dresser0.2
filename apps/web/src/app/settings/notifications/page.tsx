'use client';

/**
 * /settings/notifications — notification preferences (§7 · P10).
 *
 * DEVICE-ONLY (labeled): there is NO notifications backend — no push service, no
 * scheduler, no email fallback wired. So every toggle and the quiet-hours window
 * persist to localStorage on this device only and don't actually schedule or
 * deliver anything. The copy says so; we never imply a notification will fire.
 */

import { useEffect, useState } from 'react';
import { Bell, Hourglass, Mail, Store, Sun } from 'lucide-react';
import { useRequireAuth } from '@/lib/auth/useRequireAuth';
import { AppShell } from '@/components/layout/AppShell';
import { DSSwitch, M, RadioRow, Sheet, TopBar } from '@/components/ds';

type ToggleKey = 'dailyLook' | 'newFinds' | 'priceDrops';

interface ToggleDef {
  key: ToggleKey;
  icon: React.ReactNode;
  label: string;
  sub: string;
  default: boolean;
}

const TOGGLES: ToggleDef[] = [
  { key: 'dailyLook', icon: <Sun size={16} />, label: 'Daily look', sub: '7:00 · weather-aware outfit', default: true },
  { key: 'newFinds', icon: <Mail size={16} />, label: 'New finds to review', sub: 'When receipts arrive', default: true },
  { key: 'priceDrops', icon: <Store size={16} />, label: 'Price drops', sub: 'Saved pieces only', default: false },
];

const QUIET_OPTIONS = [
  { id: 'off', label: 'Off', sub: 'No quiet window' },
  { id: '22-7', label: '22:00 – 7:00', sub: 'Overnight' },
  { id: '23-8', label: '23:00 – 8:00' },
  { id: '0-6', label: '00:00 – 6:00' },
] as const;

const STORAGE_KEY = 'tailor.pref.notifications';

interface NotifPrefs {
  toggles: Record<ToggleKey, boolean>;
  quiet: string;
}

function defaultPrefs(): NotifPrefs {
  return {
    toggles: TOGGLES.reduce(
      (acc, t) => ({ ...acc, [t.key]: t.default }),
      {} as Record<ToggleKey, boolean>,
    ),
    quiet: '22-7',
  };
}

function Group({ children }: { children: React.ReactNode }) {
  return <div style={{ ...M.glass(24), padding: '4px 16px' }}>{children}</div>;
}

export default function NotificationsPage() {
  const { session, loading } = useRequireAuth();
  const [prefs, setPrefs] = useState<NotifPrefs>(defaultPrefs);
  const [quietOpen, setQuietOpen] = useState(false);

  useEffect(() => {
    try {
      const raw = window.localStorage.getItem(STORAGE_KEY);
      if (raw) {
        const saved = JSON.parse(raw) as Partial<NotifPrefs>;
        setPrefs((p) => ({
          toggles: { ...p.toggles, ...(saved.toggles ?? {}) },
          quiet: saved.quiet ?? p.quiet,
        }));
      }
    } catch {
      /* keep defaults */
    }
  }, []);

  const persist = (next: NotifPrefs) => {
    setPrefs(next);
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
    } catch {
      /* in-memory only */
    }
  };

  if (loading || !session) return null;

  const setToggle = (key: ToggleKey, value: boolean) =>
    persist({ ...prefs, toggles: { ...prefs.toggles, [key]: value } });

  const quietLabel = QUIET_OPTIONS.find((o) => o.id === prefs.quiet)?.label ?? 'Off';

  return (
    <AppShell>
      <div style={{ padding: '62px 20px 40px' }}>
        <TopBar title="Notifications" />
        <div className="h-4" />

        <div className="flex flex-col" style={{ gap: 12 }}>
          <Group>
            {TOGGLES.map((t, i) => (
              <div
                key={t.key}
                className="flex items-center gap-3.5 py-3.5"
                style={{ borderTop: i === 0 ? 'none' : '1px solid var(--tr-10)' }}
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
                  {t.icon}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block text-[14.5px] font-medium text-white">{t.label}</span>
                  <span className="mt-0.5 block text-[12px] leading-snug text-white/[0.55]">{t.sub}</span>
                </span>
                <DSSwitch
                  checked={prefs.toggles[t.key]}
                  aria-label={t.label}
                  onChange={(v) => setToggle(t.key, v)}
                />
              </div>
            ))}
          </Group>

          {/* Quiet hours */}
          <button
            type="button"
            onClick={() => setQuietOpen(true)}
            className="flex w-full items-center gap-3 text-left"
            style={{ ...M.glass(24), padding: '15px 16px' }}
          >
            <Hourglass size={17} style={{ color: M.faint }} />
            <span className="min-w-0 flex-1">
              <span className="block text-[13.5px] font-semibold text-white">Quiet hours</span>
              <span className="mt-px block text-[12px] text-white/[0.55]">{quietLabel}</span>
            </span>
            <ChevronRight />
          </button>
        </div>

        <div className="mt-4 flex items-start gap-2 px-0.5 text-[11.5px] leading-relaxed text-white/[0.36]">
          <Bell size={13} className="mt-px shrink-0" />
          <span>
            Saved on this device only. Push delivery isn&rsquo;t wired yet, so these choices
            won&rsquo;t send anything — they&rsquo;ll apply once notifications ship.
          </span>
        </div>
      </div>

      {/* Quiet-hours picker (DEVICE-ONLY). */}
      <Sheet
        open={quietOpen}
        onClose={() => setQuietOpen(false)}
        title="Quiet hours"
        sub="Saved on this device — when Tailor would hold notifications"
      >
        {QUIET_OPTIONS.map((o, i) => (
          <RadioRow
            key={o.id}
            first={i === 0}
            label={o.label}
            sub={'sub' in o ? o.sub : undefined}
            on={prefs.quiet === o.id}
            onSelect={() => {
              persist({ ...prefs, quiet: o.id });
              setQuietOpen(false);
            }}
          />
        ))}
      </Sheet>
    </AppShell>
  );
}

function ChevronRight() {
  return (
    <svg
      width={16}
      height={16}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      className="shrink-0 text-white/[0.36]"
      aria-hidden
    >
      <path d="M9 18l6-6-6-6" />
    </svg>
  );
}
