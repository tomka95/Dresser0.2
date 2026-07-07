'use client';

/**
 * /settings/budget — budget bands (§7 · P13). Comfort zone, not a hard wall.
 *
 * DEVICE-ONLY (labeled): there is no budget preference in the ranker yet, so the
 * chosen bands persist to localStorage on this device and don't actually filter
 * or reprice the shop feed. Copy is honest: bands set a "comfort zone", never a
 * wall, and splurge-worthy exceptions would still appear — but none of it is
 * wired to suggestions today.
 */

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { Wallet } from 'lucide-react';
import { useRequireAuth } from '@/lib/auth/useRequireAuth';
import { AppShell } from '@/components/layout/AppShell';
import { Btn, M, TopBar, useToastStore } from '@/components/ds';

interface BandDef {
  key: string;
  label: string;
  options: string[];
  default: number;
}

const BANDS: BandDef[] = [
  { key: 'tops', label: 'Tops', options: ['<$40', '$40–90', '$90+'], default: 1 },
  { key: 'outerwear', label: 'Outerwear', options: ['<$150', '$150–400', '$400+'], default: 1 },
  { key: 'shoes', label: 'Shoes', options: ['<$100', '$100–250', '$250+'], default: 1 },
];

const STORAGE_KEY = 'tailor.pref.budget';

export default function BudgetBandsPage() {
  const router = useRouter();
  const { session, loading } = useRequireAuth();
  const toast = useToastStore((s) => s.toast);
  const [selected, setSelected] = useState<Record<string, number>>(() =>
    BANDS.reduce((acc, b) => ({ ...acc, [b.key]: b.default }), {} as Record<string, number>),
  );

  useEffect(() => {
    try {
      const raw = window.localStorage.getItem(STORAGE_KEY);
      if (raw) {
        const saved = JSON.parse(raw) as Record<string, number>;
        setSelected((cur) => ({ ...cur, ...saved }));
      }
    } catch {
      /* keep defaults */
    }
  }, []);

  if (loading || !session) return null;

  const save = () => {
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(selected));
    } catch {
      /* in-memory only */
    }
    toast({ tone: 'success', title: 'Budget bands saved' });
    router.back();
  };

  return (
    <AppShell>
      <div style={{ padding: '62px 20px 40px' }}>
        <TopBar title="Budget bands" sub="A comfort zone — never a hard wall" />
        <div className="h-4" />

        <div className="flex items-start gap-2.5 rounded-2xl" style={{ padding: '12px 14px', ...M.glass(18) }}>
          <Wallet size={16} style={{ color: M.faint, marginTop: 1, flexShrink: 0 }} />
          <span className="text-[12.8px] leading-snug text-white/[0.78]">
            Sets where the shop feels comfortable. Splurge-worthy exceptions would still appear —
            labeled.
          </span>
        </div>

        <div className="mt-5 flex flex-col gap-5">
          {BANDS.map((b) => (
            <div key={b.key}>
              <div className="mb-2 text-[13.5px] font-semibold text-white">{b.label}</div>
              <div className="flex gap-2">
                {b.options.map((opt, i) => {
                  const on = selected[b.key] === i;
                  return (
                    <button
                      key={opt}
                      type="button"
                      aria-pressed={on}
                      onClick={() => setSelected((s) => ({ ...s, [b.key]: i }))}
                      className="flex-1 rounded-full py-2.5 text-center text-[12.5px] font-semibold transition-colors"
                      style={
                        on
                          ? {
                              background: 'linear-gradient(165deg, #10635c, #0a3633)',
                              color: '#fff',
                              border: '1px solid rgba(255,255,255,0.2)',
                              boxShadow: 'inset 0 1px 0 rgba(255,255,255,0.14)',
                            }
                          : {
                              background: 'rgba(255,255,255,0.07)',
                              color: M.soft,
                              border: '1px solid rgba(255,255,255,0.12)',
                            }
                      }
                    >
                      {opt}
                    </button>
                  );
                })}
              </div>
            </div>
          ))}
        </div>

        <div className="mt-5 text-[11.5px] leading-relaxed text-white/[0.36]">
          Saved on this device only — bands don&rsquo;t yet shape the shop feed.
        </div>

        <Btn variant="primary" fullWidth size="lg" className="mt-5" onClick={save}>
          Save bands
        </Btn>
      </div>
    </AppShell>
  );
}
