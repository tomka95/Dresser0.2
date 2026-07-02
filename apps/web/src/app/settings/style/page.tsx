'use client';

/**
 * /settings/style — style preferences (chips + colors). LOCAL-ONLY (persisted to
 * localStorage; no preferences backend yet).
 */

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { useRequireAuth } from '@/lib/auth/useRequireAuth';
import { AppShell } from '@/components/layout/AppShell';
import { DSBadge, DSButton, TopBar } from '@/components/ds';

const PREFS = ['Minimal', 'Street', 'Classic', 'Smart casual', 'Athleisure', 'Tailored', 'Vintage', 'Bold', 'Monochrome', 'Earthy'];
const COLORS = ['#1a1a1a', '#f5f5f0', '#7d6b56', '#3a4a5a', '#8a3a3a'];

const STORAGE_KEY = 'tailor.pref.style';

export default function StylePreferencesPage() {
  const router = useRouter();
  const { session, loading } = useRequireAuth();
  const [selected, setSelected] = useState<Record<string, boolean>>({});
  const [colors, setColors] = useState<Record<string, boolean>>({});
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    try {
      const raw = window.localStorage.getItem(STORAGE_KEY);
      if (raw) {
        const data = JSON.parse(raw) as { styles?: Record<string, boolean>; colors?: Record<string, boolean> };
        if (data.styles) setSelected(data.styles);
        if (data.colors) setColors(data.colors);
      }
    } catch {
      /* keep defaults */
    }
  }, []);

  if (loading || !session) return null;

  const handleSave = () => {
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify({ styles: selected, colors }));
    } catch {
      /* in-memory only */
    }
    setSaved(true);
    setTimeout(() => router.back(), 600);
  };

  return (
    <AppShell>
      <div className="flex min-h-full flex-col" style={{ padding: '48px 24px 40px' }}>
        <TopBar title="Style preferences" />
        <div className="h-[18px]" />
        <p className="m-0 mb-[18px] text-[14.5px] leading-relaxed text-white/70">
          Tap the styles you gravitate to. Suggestions and outfits tune to match.
        </p>
        <div className="flex flex-wrap gap-2.5">
          {PREFS.map((p) => (
            <DSBadge
              key={p}
              dark
              interactive
              selected={!!selected[p]}
              className="text-[14px]"
              style={{ padding: '10px 16px' }}
              role="button"
              tabIndex={0}
              onClick={() => setSelected((s) => ({ ...s, [p]: !s[p] }))}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') setSelected((s) => ({ ...s, [p]: !s[p] }));
              }}
            >
              {p}
            </DSBadge>
          ))}
        </div>

        <div
          className="mx-0.5 mb-3 mt-[26px] text-[12px] font-semibold uppercase tracking-[0.5px]"
          style={{ color: 'rgba(255,255,255,0.5)' }}
        >
          Colors you wear
        </div>
        <div className="flex gap-3">
          {COLORS.map((c) => {
            const on = !!colors[c];
            return (
              <button
                key={c}
                type="button"
                aria-label={`Color ${c}`}
                aria-pressed={on}
                onClick={() => setColors((s) => ({ ...s, [c]: !s[c] }))}
                className="rounded-full transition-shadow"
                style={{
                  width: 44,
                  height: 44,
                  background: c,
                  border: on ? '2px solid var(--mint)' : '1px solid var(--tr-20)',
                  boxShadow: on ? '0 0 0 3px rgba(75,226,214,0.18)' : 'none',
                }}
              />
            );
          })}
        </div>

        <div className="flex-1" />
        <DSButton variant="light" fullWidth pill className="mt-6" onClick={handleSave}>
          {saved ? 'Saved ✓' : 'Save preferences'}
        </DSButton>
      </div>
    </AppShell>
  );
}
