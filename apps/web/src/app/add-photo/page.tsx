'use client';

/**
 * /add-photo — photo -> closet ingestion entry (Wave 1.5, mobile-web).
 *
 * Pick/capture photos of yourself; the backend detects garment regions, the user
 * chooses which to keep (and can draw missed ones) in the RegionSelector, and the
 * commit routes to /review — the existing swipe deck — where the staged photo
 * candidates are reviewed and confirmed exactly like Gmail imports.
 */
import { useState } from 'react';
import { useRouter } from 'next/navigation';

import { useRequireAuth } from '@/lib/auth/useRequireAuth';
import { AppShell } from '@/components/layout/AppShell';
import { PhotoIngestUpload } from '@/components/closet/PhotoIngestUpload';
import { TopBar } from '@/components/ds';

const DEFAULT_SUB = 'We’ll spot your clothes — you choose what to add';

export default function AddPhotoPage() {
  const router = useRouter();
  const { status } = useRequireAuth();
  // Mirrored from PhotoIngestUpload so the TopBar sub can show "N of M" while a multi-photo
  // batch is being scanned; falls back to the default guidance line otherwise.
  const [phase, setPhase] = useState<{ step: string; index: number; total: number } | null>(null);
  const sub =
    phase && phase.step === 'detecting' && phase.total > 1
      ? `${Math.min(phase.index + 1, phase.total)} of ${phase.total}`
      : DEFAULT_SUB;

  if (status === 'loading' || status !== 'authenticated') {
    return (
      <AppShell scroll={false}>
        <div />
      </AppShell>
    );
  }

  return (
    <AppShell scroll={false}>
      <div className="flex h-full flex-col px-5 pt-[62px] pb-8">
        <TopBar title="Add from photo" sub={sub} onBack={() => router.back()} />
        <div className="mt-6 flex min-h-0 flex-1 flex-col">
          <PhotoIngestUpload onPhaseChange={setPhase} />
        </div>
      </div>
    </AppShell>
  );
}
