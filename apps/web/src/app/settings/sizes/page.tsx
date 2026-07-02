'use client';

/**
 * /settings/sizes — sizes & preferred fit. LOCAL-ONLY preferences (persisted to
 * localStorage; no user-preferences backend yet).
 */

import { useEffect, useState } from 'react';
import { ChevronRight } from 'lucide-react';
import { useRequireAuth } from '@/lib/auth/useRequireAuth';
import { AppShell } from '@/components/layout/AppShell';
import { RadioRow, Sheet, TopBar } from '@/components/ds';

type SizeKey = 'tops' | 'bottoms' | 'shoes' | 'outerwear';

const SIZE_ROWS: { key: SizeKey; label: string; options: string[] }[] = [
  { key: 'tops', label: 'Tops', options: ['XS', 'S', 'M', 'L', 'XL', 'XXL'] },
  { key: 'bottoms', label: 'Bottoms / waist', options: ['28', '30', '32', '34', '36', '38'] },
  { key: 'shoes', label: 'Shoes', options: ['EU 40', 'EU 41', 'EU 42', 'EU 43', 'EU 44', 'EU 45'] },
  { key: 'outerwear', label: 'Outerwear', options: ['XS', 'S', 'M', 'L', 'XL', 'XXL'] },
];

const FITS = ['Slim', 'Regular', 'Relaxed'] as const;

const DEFAULT_SIZES: Record<SizeKey, string> = {
  tops: 'M',
  bottoms: '32',
  shoes: 'EU 43',
  outerwear: 'M',
};

const STORAGE_KEY = 'tailor.pref.sizes';

export default function SizesFitPage() {
  const { session, loading } = useRequireAuth();
  const [sizes, setSizes] = useState<Record<SizeKey, string>>(DEFAULT_SIZES);
  const [fit, setFit] = useState<string>('Regular');
  const [editing, setEditing] = useState<SizeKey | null>(null);

  useEffect(() => {
    try {
      const raw = window.localStorage.getItem(STORAGE_KEY);
      if (raw) {
        const saved = JSON.parse(raw) as { sizes?: Record<SizeKey, string>; fit?: string };
        if (saved.sizes) setSizes({ ...DEFAULT_SIZES, ...saved.sizes });
        if (saved.fit) setFit(saved.fit);
      }
    } catch {
      /* keep defaults */
    }
  }, []);

  const persist = (nextSizes: Record<SizeKey, string>, nextFit: string) => {
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify({ sizes: nextSizes, fit: nextFit }));
    } catch {
      /* in-memory only */
    }
  };

  if (loading || !session) return null;

  const editingRow = SIZE_ROWS.find((r) => r.key === editing);

  return (
    <AppShell>
      <div style={{ padding: '48px 24px 40px' }}>
        <TopBar title="Sizes & fit" />
        <div className="h-[18px]" />

        <div
          className="mx-0.5 mb-3 text-[12px] font-semibold uppercase tracking-[0.5px]"
          style={{ color: 'rgba(255,255,255,0.5)' }}
        >
          Your sizes
        </div>
        <div className="flex flex-col gap-2.5">
          {SIZE_ROWS.map((row) => (
            <button
              key={row.key}
              type="button"
              onClick={() => setEditing(row.key)}
              className="flex w-full items-center gap-3 rounded-[14px] text-left"
              style={{ padding: '15px 16px', background: 'var(--tr-10)', border: '1px solid var(--tr-20)' }}
            >
              <span className="flex-1 text-[15px] text-white">{row.label}</span>
              <span className="text-[15px] font-semibold text-white">{sizes[row.key]}</span>
              <ChevronRight size={17} className="text-white/60" />
            </button>
          ))}
        </div>

        <div
          className="mx-0.5 mb-3 mt-6 text-[12px] font-semibold uppercase tracking-[0.5px]"
          style={{ color: 'rgba(255,255,255,0.5)' }}
        >
          Preferred fit
        </div>
        <div className="flex gap-2.5">
          {FITS.map((f) => {
            const on = fit === f;
            return (
              <button
                key={f}
                type="button"
                onClick={() => {
                  setFit(f);
                  persist(sizes, f);
                }}
                className="flex-1 rounded-xl py-[13px] text-center text-[14px] font-semibold transition-colors"
                style={{
                  color: on ? 'var(--brand-teal)' : '#fff',
                  background: on ? 'var(--mint)' : 'var(--tr-10)',
                  border: `1px solid ${on ? 'transparent' : 'var(--tr-20)'}`,
                }}
              >
                {f}
              </button>
            );
          })}
        </div>

        <div
          className="mt-[22px] flex items-start gap-2.5 rounded-xl"
          style={{ padding: '13px 14px', background: 'var(--grad-ai)', border: '1px solid var(--tr-20)' }}
        >
          <span style={{ color: 'var(--mint)' }}>✦</span>
          <span className="text-[13px] leading-snug text-white/85">
            Tailor uses these to flag items that won&rsquo;t fit and to size shopping suggestions.
          </span>
        </div>
      </div>

      {/* Size picker sheet */}
      <Sheet open={editing !== null} onClose={() => setEditing(null)} title={editingRow?.label}>
        {editingRow?.options.map((opt, i) => (
          <RadioRow
            key={opt}
            first={i === 0}
            label={opt}
            on={sizes[editingRow.key] === opt}
            onSelect={() => {
              const next = { ...sizes, [editingRow.key]: opt };
              setSizes(next);
              persist(next, fit);
              setEditing(null);
            }}
          />
        ))}
      </Sheet>
    </AppShell>
  );
}
