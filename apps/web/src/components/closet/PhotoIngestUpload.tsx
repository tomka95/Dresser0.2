'use client';

/**
 * PhotoIngestUpload — photo → closet ingestion, Wave 1.5 (detect → select → commit).
 *
 * The old one-shot upload auto-staged every detected garment. Now it's a small
 * state machine:
 *   pick       — choose/capture up to 10 photos (client-side validation + previews);
 *   detecting  — POST /photo/ingest/detect finds garment regions per photo;
 *   select     — RegionSelector: toggle detected regions on/off, draw missed ones;
 *   committing — POST /photo/ingest/commit re-uploads the SAME File objects (the
 *                server re-matches them by content hash) + the selections, then
 *                routes to the /review swipe deck scoped to the new run.
 *
 * Files arrive two ways: picked here, or handed off in-memory from AddItemDrawer
 * via usePhotoPickStore (Files can't cross a navigation in a URL) — those jump
 * straight to detection. Object URLs are revoked on reset and on unmount.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import { Camera, ImagePlus, X } from 'lucide-react';

import {
  commitPhotoIngest,
  detectPhotoIngest,
  PhotoSessionExpiredError,
  type PhotoCommitSelection,
  type PhotoDetectSession,
} from '@/lib/api/gmail';
import { useClosetStore } from '@/stores/useClosetStore';
import { usePhotoPickStore } from '@/stores/usePhotoPickStore';
import { RegionSelector } from './RegionSelector';

type Step = 'pick' | 'detecting' | 'select' | 'committing';

const MAX_FILE_SIZE = 10 * 1024 * 1024; // 10MB — mirrors the backend cap
const MAX_FILES = 10;
const ACCEPTED = ['image/jpeg', 'image/jpg', 'image/png', 'image/webp'];

interface Picked {
  id: number;
  file: File;
  previewUrl: string;
}

// Module-level id: object URLs aren't unique under the test stub, so keys use this.
let pickedSeq = 0;

export function PhotoIngestUpload() {
  const router = useRouter();
  const [picked, setPicked] = useState<Picked[]>([]);
  const [step, setStep] = useState<Step>('pick');
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  // Detect sessions, index-aligned with `picked` (the API returns them in file order).
  const [sessions, setSessions] = useState<PhotoDetectSession[] | null>(null);

  const galleryRef = useRef<HTMLInputElement>(null);
  const cameraRef = useRef<HTMLInputElement>(null);

  // Ref mirror of `picked` so async handlers + the unmount cleanup never see a
  // stale list (and previews are always revocable exactly once each).
  const pickedRef = useRef<Picked[]>([]);
  const updatePicked = useCallback((next: Picked[]) => {
    pickedRef.current = next;
    setPicked(next);
  }, []);

  // Revoke any surviving preview object-URLs when this screen goes away (covers
  // the navigate-to-/review path; revoking an already-revoked URL is a no-op).
  useEffect(
    () => () => {
      pickedRef.current.forEach((p) => URL.revokeObjectURL(p.previewUrl));
    },
    [],
  );

  /** Validate + wrap incoming files; returns the resulting picked list. */
  const addFiles = useCallback(
    (incoming: FileList | File[] | null): Picked[] => {
      const files = Array.from(incoming ?? []);
      if (files.length === 0) return pickedRef.current;
      setError(null);
      setNotice(null);
      const next = [...pickedRef.current];
      for (const file of files) {
        if (next.length >= MAX_FILES) {
          setNotice(`Up to ${MAX_FILES} photos at a time.`);
          break;
        }
        if (!ACCEPTED.includes(file.type)) {
          setError('Please choose JPEG, PNG, or WebP images.');
          continue;
        }
        if (file.size > MAX_FILE_SIZE) {
          setError(`Each photo must be under ${MAX_FILE_SIZE / 1024 / 1024}MB.`);
          continue;
        }
        next.push({ id: ++pickedSeq, file, previewUrl: URL.createObjectURL(file) });
      }
      updatePicked(next);
      return next;
    },
    [updatePicked],
  );

  const removeAt = useCallback(
    (i: number) => {
      const prev = pickedRef.current;
      const target = prev[i];
      if (target) URL.revokeObjectURL(target.previewUrl);
      updatePicked(prev.filter((_, idx) => idx !== i));
    },
    [updatePicked],
  );

  /** Run detection on `list`. Doesn't clear `notice` — callers set/keep it (the
   *  410 auto-rescan shows its notice THROUGH the detecting spinner). */
  const runDetect = useCallback(
    async (list: Picked[]) => {
      if (list.length === 0) return;
      setStep('detecting');
      setError(null);
      setSessions(null);
      try {
        const res = await detectPhotoIngest(list.map((p) => p.file));
        const detected = res.sessions ?? [];
        // Sessions come back in file order; a mismatch means we can't align overlays.
        if (detected.length !== list.length) {
          throw new Error('Detection returned an unexpected result. Please try again.');
        }
        if (detected.every((s) => s.duplicate)) {
          // Everything is already in the closet pipeline — nothing to select.
          list.forEach((p) => URL.revokeObjectURL(p.previewUrl));
          updatePicked([]);
          setStep('pick');
          setNotice(
            detected.length > 1
              ? 'Already added — those photos are in your closet.'
              : 'Already added — that photo is in your closet.',
          );
          return;
        }
        setSessions(detected);
        setStep('select');
      } catch (err) {
        setStep('pick'); // recoverable: files stay picked, the CTA retries
        setError(err instanceof Error ? err.message : 'Failed to scan photos.');
      }
    },
    [updatePicked],
  );

  // Drawer handoff: consume Files stashed by AddItemDrawer and go straight to detect.
  useEffect(() => {
    const handoff = usePhotoPickStore.getState().takeFiles();
    if (handoff.length === 0) return;
    const list = addFiles(handoff);
    if (list.length > 0) void runDetect(list);
  }, [addFiles, runDetect]);

  const handleSubmit = useCallback(() => {
    if (pickedRef.current.length === 0 || step !== 'pick') return;
    setNotice(null);
    void runDetect(pickedRef.current);
  }, [step, runDetect]);

  const handleCancelSelect = useCallback(() => {
    // Back to pick with the files intact — the user can add/remove and re-scan.
    setSessions(null);
    setError(null);
    setNotice(null);
    setStep('pick');
  }, []);

  const handleCommit = useCallback(
    async (selections: PhotoCommitSelection[]) => {
      const sess = sessions;
      if (!sess) return;
      setStep('committing');
      setError(null);
      const list = pickedRef.current;
      // Commit re-uploads only the files backing LIVE sessions — duplicates have no
      // session for the server to hash-match, so their bytes stay home.
      const liveFiles = list
        .filter((_, i) => sess[i] && !sess[i].duplicate && sess[i].session_id)
        .map((p) => p.file);
      try {
        const res = await commitPhotoIngest(liveFiles, selections);
        useClosetStore.getState().invalidate?.();
        if (res.staged > 0) {
          // Scope the deck to THIS run so it shows only these garments. Preview
          // object-URLs are revoked by the unmount cleanup.
          router.push(`/review?sync_id=${encodeURIComponent(res.sync_id)}`);
          return;
        }
        // Nothing staged — surface why and reset to pick.
        list.forEach((p) => URL.revokeObjectURL(p.previewUrl));
        updatePicked([]);
        setSessions(null);
        setStep('pick');
        setNotice(res.message ?? 'No new items to review.');
      } catch (err) {
        if (err instanceof PhotoSessionExpiredError) {
          // Detect sessions TTL'd out server-side — transparently re-scan the same
          // files. (Selections reset to all-selected: region ids may change.)
          setNotice('That scan expired — re-scanning your photos…');
          await runDetect(list);
          return;
        }
        setStep('select'); // recoverable: selections are still on screen
        setError(err instanceof Error ? err.message : 'Failed to add items.');
      }
    },
    [sessions, router, runDetect, updatePicked],
  );

  const busy = step === 'detecting' || step === 'committing';

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-4">
      {error && (
        <div className="rounded-lg border p-3 text-sm" style={{ borderColor: 'var(--danger)', color: 'var(--danger)' }}>
          {error}
        </div>
      )}
      {notice && (
        <div className="rounded-lg px-3 py-2 text-[13px]" style={{ background: 'var(--tr-10)', color: 'rgba(255,255,255,0.75)' }}>
          {notice}
        </div>
      )}

      {step === 'detecting' && (
        <div className="flex flex-1 flex-col items-center justify-center gap-4 py-16">
          <div
            className="h-9 w-9 rounded-full"
            style={{
              border: '3px solid var(--tr-20)',
              borderTopColor: 'var(--mint)',
              animation: 'tailor-spin 0.8s linear infinite',
            }}
          />
          <div className="text-center">
            <p className="m-0 text-[16px] font-semibold text-white">Finding your clothes…</p>
            <p className="mt-1 text-[13px]" style={{ color: 'rgba(255,255,255,0.55)' }}>
              We&rsquo;ll show what we spot — you choose what to add.
            </p>
          </div>
        </div>
      )}

      {(step === 'select' || step === 'committing') && sessions && (
        <RegionSelector
          photos={picked.map((p, i) => ({ previewUrl: p.previewUrl, session: sessions[i] }))}
          committing={step === 'committing'}
          onCancel={handleCancelSelect}
          onCommit={handleCommit}
        />
      )}

      {step === 'pick' && (
        <>
          {/* Hidden inputs: gallery (multiple) + camera (capture). */}
          <input
            ref={galleryRef}
            type="file"
            accept="image/*"
            multiple
            className="hidden"
            onChange={(e) => {
              addFiles(e.target.files);
              e.currentTarget.value = '';
            }}
          />
          <input
            ref={cameraRef}
            type="file"
            accept="image/*"
            capture="environment"
            className="hidden"
            onChange={(e) => {
              addFiles(e.target.files);
              e.currentTarget.value = '';
            }}
          />

          <div className="flex gap-3">
            <button
              type="button"
              onClick={() => galleryRef.current?.click()}
              disabled={busy}
              className="flex flex-1 items-center justify-center gap-2 rounded-xl py-3 text-[14px] font-medium disabled:opacity-50"
              style={{ background: 'var(--tr-10)', border: '1px solid var(--tr-20)', color: 'white' }}
            >
              <ImagePlus size={18} /> Choose photos
            </button>
            <button
              type="button"
              onClick={() => cameraRef.current?.click()}
              disabled={busy}
              className="flex flex-1 items-center justify-center gap-2 rounded-xl py-3 text-[14px] font-medium disabled:opacity-50"
              style={{ background: 'var(--tr-10)', border: '1px solid var(--tr-20)', color: 'white' }}
            >
              <Camera size={18} /> Take photo
            </button>
          </div>

          {picked.length > 0 && (
            <div className="grid grid-cols-3 gap-2">
              {picked.map((p, i) => (
                <div key={p.id} className="relative aspect-square overflow-hidden rounded-lg" style={{ background: '#333' }}>
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img src={p.previewUrl} alt={`Selected ${i + 1}`} className="h-full w-full object-cover" />
                  <button
                    type="button"
                    onClick={() => removeAt(i)}
                    aria-label="Remove"
                    className="absolute right-1 top-1 flex h-6 w-6 items-center justify-center rounded-full"
                    style={{ background: 'rgba(0,0,0,0.6)', color: 'white' }}
                  >
                    <X size={14} />
                  </button>
                </div>
              ))}
            </div>
          )}

          <button
            type="button"
            onClick={handleSubmit}
            disabled={picked.length === 0}
            className="rounded-xl py-3.5 text-[15px] font-semibold disabled:opacity-50"
            style={{ background: 'var(--mint)', color: 'var(--brand-teal)' }}
          >
            {picked.length > 0
              ? `Find clothes in ${picked.length} photo${picked.length > 1 ? 's' : ''}`
              : 'Select photos to continue'}
          </button>
          <p className="text-center text-[12px]" style={{ color: 'rgba(255,255,255,0.5)' }}>
            Use a photo of just yourself. JPEG, PNG, or WebP, up to {MAX_FILE_SIZE / 1024 / 1024}MB each.
          </p>
        </>
      )}
    </div>
  );
}
