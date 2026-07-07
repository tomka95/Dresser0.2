'use client';

/**
 * /settings/style — "My style profile".
 *
 * PRIMARY view: "Learned from your activity" — distilled style facts, each with
 * a confidence dot + evidence line + a per-line delete (✕). This mirrors the
 * §7 · P3 design (T2_STYLE_FACTS): learned preferences you can see and forget.
 *
 * HONEST about the backend: there is NO distilled-facts endpoint exposed to the
 * client today (distillation runs server-side but isn't surfaced). So the facts
 * are seeded from a local starter list and per-line delete is LOCAL-ONLY —
 * dismissed facts are remembered in localStorage on this device, they don't
 * actually tell the ranker to forget anything. The header copy says so plainly;
 * we never claim these are live-computed or that deleting them changes
 * recommendations.
 *
 * SECONDARY view: "Tune manually" — the device-only editable archetype chips +
 * colors (unchanged from the prior pass, still localStorage-only).
 */

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import type React from 'react';
import { X } from 'lucide-react';
import { useRequireAuth } from '@/lib/auth/useRequireAuth';
import { AppShell } from '@/components/layout/AppShell';
import { Btn, M, Spark, TopBar, useToastStore } from '@/components/ds';

/* ── Learned facts (device-seeded, honest) ────────────────────────────────── */

interface StyleFact {
  id: string;
  text: string;
  conf: number;
  from: string;
}

/** Starter facts — illustrative of what distillation would surface. */
const SEED_FACTS: StyleFact[] = [
  { id: 'neutrals', text: 'You reach for neutrals — 78% of wears are white, black, beige', conf: 0.94, from: '212 wear events' },
  { id: 'fit', text: 'Slim on top, relaxed below', conf: 0.86, from: 'fit sliders + 9 swaps' },
  { id: 'logos', text: 'You avoid logos and prints', conf: 0.81, from: 'taste deck + 14 rejections' },
  { id: 'footwear', text: 'Sneakers on weekdays, boots for dinner', conf: 0.66, from: '31 outfit confirms' },
];

const DISMISSED_KEY = 'tailor.pref.dismissedFacts';

/** Confidence dot — mint when strong (≥0.7), amber when weak. */
function ConfDot({ conf }: { conf: number }) {
  const low = conf < 0.7;
  return (
    <span
      className="inline-block shrink-0 rounded-full"
      style={{
        width: 7.5,
        height: 7.5,
        background: low ? '#f0a23b' : 'var(--mint)',
        boxShadow: low ? '0 0 0 3px rgba(240,162,59,0.16)' : '0 0 0 3px rgba(75,226,214,0.14)',
      }}
      aria-hidden
    />
  );
}

/* ── Manual tune (device-only) ────────────────────────────────────────────── */

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

  // Learned facts, minus the ones dismissed on this device.
  const [dismissed, setDismissed] = useState<Record<string, boolean>>({});

  // Manual tune (device-only).
  const [selected, setSelected] = useState<Record<string, boolean>>({});
  const [colors, setColors] = useState<Record<string, boolean>>({});
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    try {
      const rawDismissed = window.localStorage.getItem(DISMISSED_KEY);
      if (rawDismissed) setDismissed(JSON.parse(rawDismissed) as Record<string, boolean>);
    } catch {
      /* keep defaults */
    }
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

  const facts = SEED_FACTS.filter((f) => !dismissed[f.id]);

  const dismissFact = (id: string) => {
    const next = { ...dismissed, [id]: true };
    setDismissed(next);
    try {
      window.localStorage.setItem(DISMISSED_KEY, JSON.stringify(next));
    } catch {
      /* in-memory only */
    }
    toast({ tone: 'info', title: 'Removed from this device' });
  };

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
        <TopBar title="My style profile" sub="What Tailor has picked up — yours to see" />
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
            Quiet minimal — neutral palette, relaxed fits, sneakers by day and boots by night.
          </div>
        </div>

        {/* ── PRIMARY: learned facts ──────────────────────────────────────── */}
        <div className="mb-2 mt-6 flex items-baseline justify-between px-0.5">
          <span className="text-[15.5px] font-semibold text-white">Learned from your activity</span>
          <span className="text-[11.5px]" style={{ color: M.ghost }}>
            dot = confidence
          </span>
        </div>

        {facts.length > 0 ? (
          <div className="flex flex-col" style={{ gap: 9 }}>
            {facts.map((f) => (
              <div
                key={f.id}
                className="flex items-start gap-3"
                style={{
                  padding: '13px 14px',
                  borderRadius: 18,
                  background: 'rgba(255,255,255,0.055)',
                  border: '1px solid rgba(255,255,255,0.09)',
                }}
              >
                <span style={{ marginTop: 5 }}>
                  <ConfDot conf={f.conf} />
                </span>
                <div className="min-w-0 flex-1">
                  <div className="text-[13.5px] leading-snug text-white">{f.text}</div>
                  <div className="mt-1 text-[11px]" style={{ color: M.ghost }}>
                    from {f.from} · conf {f.conf.toFixed(2)}
                  </div>
                </div>
                <button
                  type="button"
                  aria-label={`Remove: ${f.text}`}
                  onClick={() => dismissFact(f.id)}
                  className="shrink-0 rounded-full p-1 text-white/[0.36] active:scale-90"
                  style={{ transition: 'transform 200ms var(--spring)' }}
                >
                  <X size={15} />
                </button>
              </div>
            ))}
          </div>
        ) : (
          <div
            className="rounded-2xl px-4 py-5 text-center text-[13px] text-white/[0.55]"
            style={{ background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.08)' }}
          >
            You&rsquo;ve cleared every learned line on this device.
          </div>
        )}

        {/* Honest note about what these are (and aren't). */}
        <div className="mt-3.5 px-0.5 text-[12px] leading-relaxed text-white/[0.55]">
          These are illustrative for now — Tailor distills style facts from your wears and chats,
          but that feed isn&rsquo;t connected to the app yet. Removing a line hides it on this
          device only; it doesn&rsquo;t change your recommendations.
        </div>

        {/* ── SECONDARY: manual tune ──────────────────────────────────────── */}
        <div
          className="mx-0.5 mb-3 mt-7 text-[11px] font-semibold uppercase"
          style={{ letterSpacing: '0.13em', color: 'rgba(255,255,255,0.36)' }}
        >
          Tune manually
        </div>

        <div className="mx-0.5 mb-3 text-[12.5px] font-semibold text-white/[0.78]">
          Styles you like
          {chosen.length > 0 && (
            <span className="ml-2 font-normal text-white/[0.45]">{chosen.join(', ')}</span>
          )}
        </div>
        <div className="flex flex-wrap gap-2.5">
          {PREFS.map((p) => (
            <Chip key={p} on={!!selected[p]} onClick={() => setSelected((s) => ({ ...s, [p]: !s[p] }))}>
              {p}
            </Chip>
          ))}
        </div>

        <div className="mx-0.5 mb-3 mt-[26px] text-[12.5px] font-semibold text-white/[0.78]">
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
          Manual tweaks are saved on this device — not yet feeding recommendations.
        </div>

        <Btn variant="primary" fullWidth size="lg" className="mt-6" pending={saving} onClick={handleSave}>
          Save style profile
        </Btn>
      </div>
    </AppShell>
  );
}
