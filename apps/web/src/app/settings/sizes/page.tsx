'use client';

/**
 * /settings/sizes — sizes & preferred fit.
 *
 * SOURCE OF TRUTH = the server. Sizes live in style_profiles.facts (the same
 * place onboarding wrote them and the closet/composer read them); this screen
 * reads/writes them through GET/PATCH /profile/style. The old device-only
 * `tailor.pref.sizes` localStorage key is migrated on first load (pushed up if
 * the server has nothing yet) and then DISCARDED — no more divergence. Closes
 * part of SCRUM-49.
 */

import { useCallback, useEffect, useState } from 'react';
import { ChevronRight } from 'lucide-react';
import { LETTER_SIZES, type SizeProfile } from '@tailor/contracts';
import { useRequireAuth } from '@/lib/auth/useRequireAuth';
import { AppShell } from '@/components/layout/AppShell';
import { M, RadioRow, Sheet, Sk, TopBar, useToastStore } from '@/components/ds';
import { getStyleProfile, patchStyleProfile, type StyleFacts } from '@/lib/api/profile';

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

const LEGACY_KEY = 'tailor.pref.sizes';

/* ── mapping between the flat display strings and the structured SizeProfile ── */

function isLetter(v: string): v is (typeof LETTER_SIZES)[number] {
  return (LETTER_SIZES as readonly string[]).includes(v);
}

/** Structured facts.sizes -> the flat display strings this screen renders. */
function toFlat(sp: SizeProfile | undefined): Record<SizeKey, string> {
  const out = { ...DEFAULT_SIZES };
  if (!sp) return out;
  if (sp.top) out.tops = sp.top;
  if (sp.outerwear) out.outerwear = sp.outerwear;
  if (sp.bottom?.system === 'waist_inseam') out.bottoms = String(sp.bottom.waist);
  if (sp.shoe) out.shoes = `${sp.shoe.system} ${sp.shoe.value}`;
  return out;
}

/** The flat display strings -> a structured SizeProfile for the server. */
function toSizeProfile(flat: Record<SizeKey, string>): SizeProfile {
  const sp: SizeProfile = {};
  if (isLetter(flat.tops)) sp.top = flat.tops;
  if (isLetter(flat.outerwear)) sp.outerwear = flat.outerwear;
  const waist = parseInt(flat.bottoms, 10);
  if (!Number.isNaN(waist)) sp.bottom = { system: 'waist_inseam', waist };
  const [system, value] = flat.shoes.split(' ');
  if ((system === 'EU' || system === 'US' || system === 'UK') && value) {
    sp.shoe = { system, value };
  }
  return sp;
}

export default function SizesFitPage() {
  const { session, loading: authLoading } = useRequireAuth();
  const toast = useToastStore((s) => s.toast);

  const [sizes, setSizes] = useState<Record<SizeKey, string>>(DEFAULT_SIZES);
  const [fit, setFit] = useState<string>('Regular');
  const [editing, setEditing] = useState<SizeKey | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    let serverFacts: StyleFacts = {};
    try {
      serverFacts = (await getStyleProfile()).facts;
    } catch {
      // fall through to whatever we can read locally / defaults
    }

    // One-time migration: if the server has no sizes yet but this device holds
    // the legacy localStorage copy, push it up so nothing is lost.
    let legacy: { sizes?: Partial<Record<SizeKey, string>>; fit?: string } | null = null;
    try {
      const raw = window.localStorage.getItem(LEGACY_KEY);
      if (raw) legacy = JSON.parse(raw);
    } catch {
      /* ignore */
    }

    if (!serverFacts.sizes && legacy?.sizes) {
      const flat = { ...DEFAULT_SIZES, ...legacy.sizes } as Record<SizeKey, string>;
      try {
        const patched = await patchStyleProfile({
          facts: { sizes: toSizeProfile(flat), fit_preference: legacy.fit || 'Regular' },
        });
        serverFacts = patched.facts;
      } catch {
        // keep local values in state if the push failed; still discard the key below
        setSizes(flat);
        if (legacy.fit) setFit(legacy.fit);
      }
    }

    // Discard the legacy device-only key regardless — the server is now canonical.
    try {
      window.localStorage.removeItem(LEGACY_KEY);
    } catch {
      /* ignore */
    }

    if (serverFacts.sizes) setSizes(toFlat(serverFacts.sizes));
    if (typeof serverFacts.fit_preference === 'string') setFit(serverFacts.fit_preference);
    setLoading(false);
  }, []);

  const authed = !!session;
  useEffect(() => {
    if (authed) void load();
  }, [authed, load]);

  if (authLoading || !session) return null;

  const editingRow = SIZE_ROWS.find((r) => r.key === editing);

  const saveSizes = async (nextSizes: Record<SizeKey, string>) => {
    setSizes(nextSizes);
    try {
      await patchStyleProfile({ facts: { sizes: toSizeProfile(nextSizes) } });
    } catch {
      toast({ tone: 'error', title: "Couldn't save — try again" });
    }
  };

  const saveFit = async (nextFit: string) => {
    setFit(nextFit);
    try {
      await patchStyleProfile({ facts: { fit_preference: nextFit } });
    } catch {
      toast({ tone: 'error', title: "Couldn't save — try again" });
    }
  };

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

        {loading ? (
          <Sk h={220} r={24} />
        ) : (
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
        )}

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
                onClick={() => saveFit(f)}
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
          Saved to your Tailor profile — used to size suggestions across your devices.
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
              void saveSizes({ ...sizes, [editingRow.key]: opt });
              setEditing(null);
            }}
          />
        ))}
      </Sheet>
    </AppShell>
  );
}
