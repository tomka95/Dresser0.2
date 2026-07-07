'use client';

/**
 * /settings/color — color-season analysis (§7 · P12). Roadmap, consent-gated.
 *
 * ROADMAP / HONEST-DISABLED: on-device color analysis isn't built. The consent
 * screen states the privacy contract (one daylight selfie, analyzed on-device,
 * deleted, only the season kept) but the "Take the selfie" action is DISABLED
 * ("Coming soon") — we never open a camera and never fake a result. Below it, a
 * clearly-labeled SAMPLE shows what a result would look like; it is not the
 * user's season and is never presented as computed from their data.
 */

import { useRouter } from 'next/navigation';
import { Camera, Palette } from 'lucide-react';
import { useRequireAuth } from '@/lib/auth/useRequireAuth';
import { AppShell } from '@/components/layout/AppShell';
import { Btn, M, Medallion, TopBar } from '@/components/ds';

const SAMPLE_SWATCHES = ['#e8e4da', '#b9c4bd', '#7d9a94', '#31555c', '#28323c', '#8c6f5a'];

export default function ColorAnalysisPage() {
  const router = useRouter();
  const { session, loading } = useRequireAuth();

  if (loading || !session) return null;

  return (
    <AppShell>
      <div style={{ padding: '62px 20px 40px' }}>
        <TopBar title="Color analysis" />
        <div className="h-2" />

        {/* Consent — action disabled (roadmap). */}
        <div className="flex flex-col items-center px-4 pb-2 pt-6 text-center">
          <Medallion tone="mint" pulse size={92} icon={<Palette size={32} />} />
          <div className="mt-5 text-[21px] font-bold text-white" style={{ letterSpacing: '-0.5px' }}>
            Find your palette
          </div>
          <div className="mt-2 max-w-[280px] text-[13.5px] leading-relaxed text-white/[0.55]">
            One selfie in daylight. It would be analyzed on-device, then deleted — only the
            resulting season is kept, and you could remove it anytime.
          </div>
          <div className="mt-6 flex w-full max-w-[280px] flex-col gap-2.5">
            <Btn size="lg" icon={<Camera size={17} />} disabled title="On-device color analysis is coming soon">
              Coming soon
            </Btn>
            <Btn variant="ghost" size="md" onClick={() => router.back()}>
              Maybe later
            </Btn>
          </div>
          <div className="mt-3 text-[11.5px] text-white/[0.36]">
            On-device analysis isn&rsquo;t built yet — no selfie is taken and no result is produced.
          </div>
        </div>

        {/* SAMPLE result — illustrative only, clearly not the user's. */}
        <div
          className="mx-0.5 mb-2 mt-7 text-[11px] font-semibold uppercase"
          style={{ letterSpacing: '0.13em', color: 'rgba(255,255,255,0.36)' }}
        >
          Sample result
        </div>
        <div style={{ ...M.ai(26), padding: 20, textAlign: 'center' }}>
          <div
            className="text-[10px] font-semibold uppercase"
            style={{ letterSpacing: '0.13em', color: 'var(--mint)' }}
          >
            Example season
          </div>
          <div className="mt-1.5 text-[24px] font-bold text-white" style={{ letterSpacing: '-0.5px' }}>
            Soft Summer
          </div>
          <div className="mt-1 text-[12.5px]" style={{ color: M.soft }}>
            Muted, cool, low-contrast. When it ships, we&rsquo;d also show how much your closet
            agrees.
          </div>
          <div className="mt-4 flex justify-center gap-2">
            {SAMPLE_SWATCHES.map((c) => (
              <span
                key={c}
                className="rounded-full"
                style={{
                  width: 34,
                  height: 34,
                  background: c,
                  border: '2px solid rgba(255,255,255,0.25)',
                  boxShadow: '0 4px 12px rgba(0,0,0,0.3)',
                }}
              />
            ))}
          </div>
        </div>
        <div className="mt-3 text-center text-[11.5px] text-white/[0.36]">
          This is an example — not your analysis.
        </div>
      </div>
    </AppShell>
  );
}
