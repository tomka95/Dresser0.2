'use client';

/**
 * /settings/style — "My style profile": style archetype chips + colors you wear.
 *
 * DEVICE-ONLY (labeled): persisted to localStorage (tailor.pref.style). This is
 * NOT wired to the recommendation ranker yet, so the copy is honest — it does
 * not claim to tune suggestions. When a preferences backend + ranker hook exist,
 * this becomes the editable surface over what Tailor has learned.
 */

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import type React from 'react';
import { useRequireAuth } from '@/lib/auth/useRequireAuth';
import { AppShell } from '@/components/layout/AppShell';
import { Btn, M, Spark, TopBar, useToastStore } from '@/components/ds';

const PREFS = [
  'Minimal',
  'Street',
  'Classic',
  'Smart casual',
  'Athleisure',
  'Tailored',
  'Vintage',
  'Bold',
  'Monochrome',
  'Earthy',
];
const COLORS = ['#1a1a1a', '#f5f5f0', '#7d6b56', '#3a4a5a', '#8a3a3a'];

const STORAGE_KEY = 'tailor.pref.style';

function Chip({ on, children, onClick }: { on: boolean; children: React.ReactNode; onClick: () => void }) {
  return (
    <button
      type="button"
      aria-pressed={on}
      onClick={onClick}
      className="inline-flex items-center rounded-full text-[13.5px] font-medium transition-colors"
      style={{
        height: 37,
        padding: '0 16px',
        letterSpacing: '0.1px',
        ...(on
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
            }),
      }}
    >
      {children}
    </button>
  );
}

export default function StyleProfilePage() {
  const router = useRouter();
  const { session, loading } = useRequireAuth();
  const toast = useToastStore((s) => s.toast);
  const [selected, setSelected] = useState<Record<string, boolean>>({});
  const [colors, setColors] = useState<Record<string, boolean>>({});
  const [saving, setSaving] = useState(false);

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
    setSaving(true);
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify({ styles: selected, colors }));
    } catch {
      /* in-memory only */
    }
    toast({ tone: 'success', title: 'Style profile saved' });
    setTimeout(() => {
      setSaving(false);
      router.back();
    }, 500);
  };

  const chosen = PREFS.filter((p) => selected[p]);

  return (
    <AppShell>
      <div style={{ padding: '62px 20px 40px' }}>
        <TopBar title="My style profile" sub="Yours to set — see and edit it" />
        <div className="h-[18px]" />

        {/* AI-styled summary line. */}
        <div style={{ ...M.ai(24), padding: 17 }}>
          <div className="flex items-center gap-1.5">
            <Spark size={12} />
            <span
              className="text-[10px] font-semibold uppercase"
              style={{ letterSpacing: '0.13em', color: 'var(--mint)' }}
            >
              In one line
            </span>
          </div>
          <div
            className="mt-2 text-white"
            style={{ fontSize: 16.5, fontWeight: 600, lineHeight: 1.45, letterSpacing: '-0.2px' }}
          >
            {chosen.length ? chosen.join(', ') : 'Tap the styles you gravitate to below.'}
          </div>
        </div>

        <div
          className="mx-0.5 mb-3 mt-6 text-[11px] font-semibold uppercase"
          style={{ letterSpacing: '0.13em', color: 'rgba(255,255,255,0.36)' }}
        >
          Styles you like
        </div>
        <div className="flex flex-wrap gap-2.5">
          {PREFS.map((p) => (
            <Chip key={p} on={!!selected[p]} onClick={() => setSelected((s) => ({ ...s, [p]: !s[p] }))}>
              {p}
            </Chip>
          ))}
        </div>

        <div
          className="mx-0.5 mb-3 mt-[26px] text-[11px] font-semibold uppercase"
          style={{ letterSpacing: '0.13em', color: 'rgba(255,255,255,0.36)' }}
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

        <div className="mt-[22px] text-[11.5px] leading-relaxed text-white/[0.36]">
          Saved on this device — not yet feeding recommendations.
        </div>

        <Btn variant="primary" fullWidth size="lg" className="mt-6" pending={saving} onClick={handleSave}>
          Save style profile
        </Btn>
      </div>
    </AppShell>
  );
}
