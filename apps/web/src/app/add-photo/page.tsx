'use client';

/**
 * /add-photo — photo -> closet ingestion entry (Wave 1.5, mobile-web).
 *
 * Pick/capture photos of yourself; the backend detects garment regions, the user
 * chooses which to keep (and can draw missed ones) in the RegionSelector, and the
 * commit routes to /review — the existing swipe deck — where the staged photo
 * candidates are reviewed and confirmed exactly like Gmail imports.
 */
import { useRouter } from 'next/navigation';
import { ArrowLeft } from 'lucide-react';

import { useRequireAuth } from '@/lib/auth/useRequireAuth';
import { AppShell } from '@/components/layout/AppShell';
import { PhotoIngestUpload } from '@/components/closet/PhotoIngestUpload';

export default function AddPhotoPage() {
  const router = useRouter();
  const { status } = useRequireAuth();

  if (status === 'loading' || status !== 'authenticated') {
    return (
      <AppShell scroll={false}>
        <div />
      </AppShell>
    );
  }

  return (
    <AppShell scroll={false}>
      <div className="flex h-full flex-col px-5 pt-12 pb-8">
        <button
          type="button"
          onClick={() => router.back()}
          aria-label="Back"
          className="mb-4 inline-flex items-center gap-1 text-[14px]"
          style={{ color: 'rgba(255,255,255,0.6)' }}
        >
          <ArrowLeft size={18} /> Back
        </button>
        <h1 className="m-0 text-[20px] font-bold text-white">Add from a photo</h1>
        <p className="mt-1 mb-6 text-[13.5px]" style={{ color: 'rgba(255,255,255,0.6)' }}>
          We&rsquo;ll spot your clothes — you choose what to add.
        </p>
        <PhotoIngestUpload />
      </div>
    </AppShell>
  );
}
