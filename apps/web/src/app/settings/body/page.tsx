'use client';

/**
 * /settings/body — body shape (§7 · P11). Roadmap, opt-in, privacy-first.
 *
 * DEVICE-ONLY / ROADMAP: fit advice from body shape isn't built. This screen is
 * strictly opt-in, uses abstract silhouettes (never a body image), and stores
 * the choice in localStorage on this device only. The privacy banner is honest:
 * it's private to styling, never shown on a profile, and doesn't yet change any
 * suggestion. Skipping is a first-class action.
 */

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { Shield } from 'lucide-react';
import { useRequireAuth } from '@/lib/auth/useRequireAuth';
import { AppShell } from '@/components/layout/AppShell';
import { Btn, Field, M, TopBar, useToastStore } from '@/components/ds';

interface ShapeOpt {
  id: string;
  label: string;
  top: number;
  bottom: number;
}

const SHAPES: ShapeOpt[] = [
  { id: 'straight', label: 'Straight', top: 22, bottom: 22 },
  { id: 'curve', label: 'Curve', top: 18, bottom: 27 },
  { id: 'athletic', label: 'Athletic', top: 26, bottom: 19 },
  { id: 'round', label: 'Round', top: 27, bottom: 24 },
];

const STORAGE_KEY = 'tailor.pref.body';

/** Abstract two-bar silhouette — never a body image. */
function Silhouette({ top, bottom }: { top: number; bottom: number }) {
  return (
    <div className="flex flex-col items-center gap-0.5">
      <span className="rounded-md" style={{ width: top, height: 16, background: 'rgba(255,255,255,0.55)' }} />
      <span className="rounded-md" style={{ width: bottom, height: 16, background: 'rgba(255,255,255,0.55)' }} />
    </div>
  );
}

export default function BodyShapePage() {
  const router = useRouter();
  const { session, loading } = useRequireAuth();
  const toast = useToastStore((s) => s.toast);
  const [shape, setShape] = useState<string | null>(null);
  const [height, setHeight] = useState('');

  useEffect(() => {
    try {
      const raw = window.localStorage.getItem(STORAGE_KEY);
      if (raw) {
        const saved = JSON.parse(raw) as { shape?: string | null; height?: string };
        if (saved.shape) setShape(saved.shape);
        if (saved.height) setHeight(saved.height);
      }
    } catch {
      /* keep defaults */
    }
  }, []);

  if (loading || !session) return null;

  const save = () => {
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify({ shape, height }));
    } catch {
      /* in-memory only */
    }
    toast({ tone: 'success', title: 'Saved on this device' });
    router.back();
  };

  return (
    <AppShell>
      <div style={{ padding: '62px 20px 40px' }}>
        <TopBar title="Body shape" sub="Optional — for fit advice only" />
        <div className="h-4" />

        {/* Privacy-first banner. */}
        <div
          className="flex items-start gap-2.5 rounded-2xl"
          style={{ padding: '12px 14px', background: 'rgba(75,226,214,0.10)', border: '1px solid rgba(75,226,214,0.28)' }}
        >
          <Shield size={15} style={{ color: 'var(--mint)', marginTop: 1, flexShrink: 0 }} />
          <span className="text-[12.8px] leading-snug text-white">
            Private to your styling. Never shared, never shown on any profile. Skip freely — this
            is a preview and doesn&rsquo;t change suggestions yet.
          </span>
        </div>

        <div className="mt-4 grid grid-cols-2 gap-3">
          {SHAPES.map((s) => {
            const on = shape === s.id;
            return (
              <button
                key={s.id}
                type="button"
                aria-pressed={on}
                onClick={() => setShape((cur) => (cur === s.id ? null : s.id))}
                className="rounded-[22px] px-3.5 py-[18px] text-center"
                style={{
                  background: on
                    ? 'linear-gradient(165deg, rgba(16,99,92,0.5), rgba(10,54,51,0.55))'
                    : 'rgba(255,255,255,0.055)',
                  border: on ? '1.5px solid rgba(75,226,214,0.55)' : '1px solid rgba(255,255,255,0.1)',
                }}
              >
                <Silhouette top={s.top} bottom={s.bottom} />
                <div className="mt-2.5 text-[13.5px] font-semibold text-white">{s.label}</div>
              </button>
            );
          })}
        </div>

        <Field
          label="Height (optional)"
          value={height}
          onChange={setHeight}
          placeholder="e.g. 182 cm"
          className="mt-4"
        />

        <div className="mt-5 flex gap-2.5">
          <Btn variant="ghost" size="md" fullWidth onClick={() => router.back()}>
            Skip
          </Btn>
          <Btn variant="primary" size="md" fullWidth onClick={save}>
            Save
          </Btn>
        </div>

        <div className="mt-4 text-[11.5px] leading-relaxed text-white/[0.36]">
          Roadmap preview — saved on this device only. Fit advice from body shape isn&rsquo;t
          built yet.
        </div>
      </div>
    </AppShell>
  );
}
