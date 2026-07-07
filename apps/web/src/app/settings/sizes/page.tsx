'use client';

/**
 * /settings/sizes — sizes & preferred fit.
 *
 * DEVICE-ONLY (labeled): persisted to localStorage (tailor.pref.sizes). There is
 * no user-preferences backend yet, so these values live on this device and do
 * not yet feed sizing on suggestions.
 */

import { useEffect, useState } from 'react';
import { ChevronRight } from 'lucide-react';
import { useRequireAuth } from '@/lib/auth/useRequireAuth';
import { AppShell } from '@/components/layout/AppShell';
import { M, RadioRow, Sheet, TopBar } from '@/components/ds';

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
      <div style={{ padding: '62px 20px 40px' }}>
        <TopBar title="Sizes & fit" />
        <div className="h-[18px]" />

        <div
          className="mx-0.5 mb-3 text-[11px] font-semibold uppercase"
          style={{ letterSpacing: '0.13em', color: 'rgba(255,255,255,0.36)' }}
        >
          Your sizes
        </div>
        <div style={{ ...M.glass(24), padding: '4px 16px' }}>
          {SIZE_ROWS.map((row, i) => (
            <button
              key={row.key}
              type="button"
              onClick={() => setEditing(row.key)}
              className="flex w-full items-center gap-3 py-3.5 text-left"
              style={{ borderTop: i === 0 ? 'none' : '1px solid var(--tr-10)' }}
            >
              <span className="flex-1 text-[14.5px] text-white">{row.label}</span>
              <span className="text-[14.5px] font-semibold text-white">{sizes[row.key]}</span>
              <ChevronRight size={17} className="text-white/[0.36]" />
            </button>
          ))}
        </div>

        <div
          className="mx-0.5 mb-3 mt-6 text-[11px] font-semibold uppercase"
          style={{ letterSpacing: '0.13em', color: 'rgba(255,255,255,0.36)' }}
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
                className="flex-1 rounded-full py-[13px] text-center text-[14px] font-semibold transition-colors"
                style={{
                  color: on ? 'var(--brand-teal)' : '#fff',
                  background: on ? 'var(--mint)' : 'rgba(255,255,255,0.07)',
                  border: `1px solid ${on ? 'transparent' : 'var(--tr-20)'}`,
                }}
              >
                {f}
              </button>
            );
          })}
        </div>

        <div className="mt-[22px] text-[11.5px] leading-relaxed text-white/[0.36]">
          Saved on this device only — Tailor doesn&rsquo;t yet use these to size shopping
          suggestions.
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
