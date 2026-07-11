'use client';

/**
 * /settings/style — "My style profile".
 *
 * REAL now: reads the server-side brain via GET /profile/style — the distilled
 * narrative (verbatim), plus the learned per-dimension preferences with a human
 * explanation line derived from their evidence. Edits are REAL and sacred:
 *
 *   • Delete (✕)  → PATCH { preferences:[{dimension, delete:true}] } — a durable
 *                    tombstone; distillation can never re-derive that dimension.
 *   • Flip pill    → PATCH { preferences:[{dimension, polarity}] } — a user
 *                    override stamped user_edited; re-distill never overwrites it.
 *
 * Honest states: a brand-new user with a sparse profile sees a real empty state
 * (no seeded filler), not fabricated facts.
 */

import { useCallback, useEffect, useState } from 'react';
import { X } from 'lucide-react';
import { useRequireAuth } from '@/lib/auth/useRequireAuth';
import { AppShell } from '@/components/layout/AppShell';
import { Btn, ErrorState, M, Sk, SkList, Spark, StateBlock, TopBar, useToastStore } from '@/components/ds';
import {
  getStyleProfile,
  patchStyleProfile,
  type LearnedPreference,
  type StyleProfile,
} from '@/lib/api/profile';

/* ── helpers ──────────────────────────────────────────────────────────────── */

const DIMENSION_LABEL: Record<string, string> = {
  color: 'Color',
  silhouette: 'Silhouette',
  fit: 'Fit',
  formality: 'Formality',
  pattern: 'Pattern',
  material: 'Material',
  category: 'Category',
  brand: 'Brands',
  occasion: 'Occasion',
  length: 'Length',
  vibe: 'Vibe',
};

const POLARITY_WORD: Record<string, string> = { like: 'Leans into', dislike: 'Avoids', neutral: 'Noted' };

function dimensionLabel(d: string): string {
  return DIMENSION_LABEL[d] ?? d.charAt(0).toUpperCase() + d.slice(1);
}

/** A short detail line from the freeform value blob (notes/colors/styles), if any. */
function valueDetail(value: Record<string, unknown>): string | null {
  for (const key of ['notes', 'colors', 'styles', 'brands', 'items']) {
    const v = value[key];
    if (Array.isArray(v) && v.length) return v.map(String).join(', ');
  }
  const note = value['note'];
  return typeof note === 'string' && note.trim() ? note.trim() : null;
}

/** Confidence dot — mint when strong (≥0.7), amber when weak. */
function ConfDot({ conf }: { conf: number | null }) {
  const low = conf != null && conf < 0.7;
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

export default function StyleProfilePage() {
  const { session, loading: authLoading } = useRequireAuth();
  const toast = useToastStore((s) => s.toast);

  const [profile, setProfile] = useState<StyleProfile | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [busy, setBusy] = useState<Record<string, boolean>>({});

  const load = useCallback(async () => {
    setLoading(true);
    setError(false);
    try {
      setProfile(await getStyleProfile());
    } catch {
      setError(true);
    } finally {
      setLoading(false);
    }
  }, []);

  const authed = !!session;
  useEffect(() => {
    if (authed) void load();
  }, [authed, load]);

  if (authLoading || !session) return null;

  const prefs = profile?.preferences ?? [];

  const applyEdit = async (dimension: string, edit: { delete?: boolean; polarity?: 'like' | 'dislike' }) => {
    setBusy((b) => ({ ...b, [dimension]: true }));
    try {
      const next = await patchStyleProfile({ preferences: [{ dimension, ...edit }] });
      setProfile(next);
      toast({ tone: edit.delete ? 'info' : 'success', title: edit.delete ? 'Forgotten' : 'Updated' });
    } catch {
      toast({ tone: 'error', title: "Couldn't save — try again" });
    } finally {
      setBusy((b) => ({ ...b, [dimension]: false }));
    }
  };

  const forget = (p: LearnedPreference) => applyEdit(p.dimension, { delete: true });
  const flip = (p: LearnedPreference) =>
    applyEdit(p.dimension, { polarity: p.polarity === 'dislike' ? 'like' : 'dislike' });

  return (
    <AppShell>
      <div style={{ padding: '62px 20px 40px' }}>
        <TopBar title="My style profile" sub="What Tailor has picked up — yours to see" />
        <div className="h-[18px]" />

        {loading ? (
          <div className="flex flex-col gap-4">
            <Sk h={78} r={24} />
            <SkList n={4} />
          </div>
        ) : error ? (
          <ErrorState
            title="Couldn’t load your profile"
            sub="Your data is safe. Give it another try."
            onRetry={load}
          />
        ) : (
          <>
            {/* Distilled narrative — verbatim, only when one exists. */}
            {profile?.narrative && (
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
                  {profile.narrative}
                </div>
              </div>
            )}

            <div className="mb-2 mt-6 flex items-baseline justify-between px-0.5">
              <span className="text-[15.5px] font-semibold text-white">Learned about your style</span>
              {prefs.length > 0 && (
                <span className="text-[11.5px]" style={{ color: M.ghost }}>
                  dot = confidence
                </span>
              )}
            </div>

            {prefs.length > 0 ? (
              <div className="flex flex-col" style={{ gap: 9 }}>
                {prefs.map((p) => {
                  const detail = valueDetail(p.value);
                  const word = POLARITY_WORD[p.polarity ?? 'neutral'] ?? 'Noted';
                  return (
                    <div
                      key={p.dimension}
                      className="flex items-start gap-3"
                      style={{
                        padding: '13px 14px',
                        borderRadius: 18,
                        background: 'rgba(255,255,255,0.055)',
                        border: '1px solid rgba(255,255,255,0.09)',
                        opacity: busy[p.dimension] ? 0.5 : 1,
                        transition: 'opacity 160ms ease',
                      }}
                    >
                      <span style={{ marginTop: 5 }}>
                        <ConfDot conf={p.confidence} />
                      </span>
                      <div className="min-w-0 flex-1">
                        <div className="text-[13.5px] leading-snug text-white">
                          <span style={{ color: M.soft }}>{word} </span>
                          {dimensionLabel(p.dimension).toLowerCase()}
                          {detail ? <span className="text-white/[0.85]"> — {detail}</span> : null}
                        </div>
                        <div className="mt-1 text-[11px]" style={{ color: M.ghost }}>
                          <span>{p.explanation}</span>
                          {p.confidence != null ? <span>{` · conf ${p.confidence.toFixed(2)}`}</span> : null}
                        </div>
                      </div>
                      {/* Flip like/dislike (a sacred override). */}
                      {p.polarity === 'like' || p.polarity === 'dislike' ? (
                        <button
                          type="button"
                          disabled={busy[p.dimension]}
                          aria-label={`Change to ${p.polarity === 'dislike' ? 'like' : 'dislike'}: ${dimensionLabel(p.dimension)}`}
                          onClick={() => flip(p)}
                          className="shrink-0 rounded-full text-[11px] font-medium active:scale-95"
                          style={{
                            padding: '4px 9px',
                            color: p.polarity === 'dislike' ? '#f0a23b' : 'var(--mint)',
                            background: 'rgba(255,255,255,0.06)',
                            border: '1px solid rgba(255,255,255,0.12)',
                            transition: 'transform 200ms var(--spring)',
                          }}
                        >
                          {p.polarity === 'dislike' ? 'Dislike' : 'Like'}
                        </button>
                      ) : null}
                      <button
                        type="button"
                        disabled={busy[p.dimension]}
                        aria-label={`Forget: ${dimensionLabel(p.dimension)}`}
                        onClick={() => forget(p)}
                        className="shrink-0 rounded-full p-1 text-white/[0.36] active:scale-90"
                        style={{ transition: 'transform 200ms var(--spring)' }}
                      >
                        <X size={15} />
                      </button>
                    </div>
                  );
                })}
              </div>
            ) : (
              <StateBlock
                compact
                tone="mint"
                icon={<Spark size={20} />}
                title="Still learning your style"
                sub="Chat with the stylist, log what you wear, and swipe the taste deck — the preferences Tailor picks up will show here, and you’ll be able to correct them."
              />
            )}

            {/* Honest note about what these are. */}
            {prefs.length > 0 && (
              <div className="mt-3.5 px-0.5 text-[12px] leading-relaxed text-white/[0.55]">
                These are distilled from your wears, chats, and taste swipes. Removing a line tells
                Tailor to forget it for good; changing like/dislike sticks and won’t be relearned over.
              </div>
            )}

            <Btn variant="ghost" fullWidth size="lg" className="mt-7" onClick={load}>
              Refresh
            </Btn>
          </>
        )}
      </div>
    </AppShell>
  );
}
