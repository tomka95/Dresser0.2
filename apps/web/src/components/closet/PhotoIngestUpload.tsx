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
import { useGenerationStore } from '@/stores/useGenerationStore';
import { HeicTranscodeError, looksLikeHeic, transcodeHeicToJpeg } from '@/lib/image/heic';
import { RegionSelector } from './RegionSelector';
import { GenerationProgressPill } from './GenerationProgressPill';

// 'preparing' = commit succeeded and product cards are generating in the background; the
// non-blocking pill lets the user review whenever they choose (never a forced navigation).
type Step = 'pick' | 'detecting' | 'select' | 'committing' | 'preparing';

const MAX_FILE_SIZE = 10 * 1024 * 1024; // 10MB — mirrors the backend cap
const MAX_FILES = 10;
// Formats accepted as-is. HEIC/HEIF are also accepted but transcoded to JPEG first
// (see addFiles), so by the time a file is uploaded it is always one of these.
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
  // After a successful commit, the run whose product cards are generating — drives the
  // non-blocking "Preparing N → Review" pill (step 'preparing').
  const [genRun, setGenRun] = useState<{ syncId: string; staged: number } | null>(null);
  // True while a HEIC/HEIF file is being transcoded to JPEG (async, can be slow on
  // large photos) — drives a lightweight "preparing" affordance so the UI isn't frozen.
  const [preparing, setPreparing] = useState(false);
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

  /**
   * Validate + wrap incoming files; returns the resulting picked list.
   *
   * HEIC/HEIF files are transcoded to JPEG HERE, once, before being wrapped — the
   * transcoded File is what gets stored, previewed, hashed (server-side) and
   * re-uploaded at commit, so detect and commit always see byte-identical bytes.
   * The size cap is checked on the FINAL bytes (what actually uploads).
   */
  const addFiles = useCallback(
    async (incoming: FileList | File[] | null): Promise<Picked[]> => {
      const files = Array.from(incoming ?? []);
      if (files.length === 0) return pickedRef.current;
      setError(null);
      setNotice(null);
      const needsTranscode = files.some(looksLikeHeic);
      if (needsTranscode) setPreparing(true);
      const next = [...pickedRef.current];
      try {
        for (const incomingFile of files) {
          if (next.length >= MAX_FILES) {
            setNotice(`Up to ${MAX_FILES} photos at a time.`);
            break;
          }
          const isHeic = looksLikeHeic(incomingFile);
          if (!ACCEPTED.includes(incomingFile.type) && !isHeic) {
            setError('Please choose JPEG, PNG, WebP, or HEIC images.');
            continue;
          }
          let file = incomingFile;
          if (isHeic) {
            try {
              // Transcode ONCE — this JPEG is now the canonical file everywhere.
              file = await transcodeHeicToJpeg(incomingFile);
            } catch (err) {
              setError(
                err instanceof HeicTranscodeError
                  ? err.message
                  : "We couldn't read that HEIC photo. Try exporting it as JPEG.",
              );
              continue;
            }
          }
          if (file.size > MAX_FILE_SIZE) {
            setError(`Each photo must be under ${MAX_FILE_SIZE / 1024 / 1024}MB.`);
            continue;
          }
          next.push({ id: ++pickedSeq, file, previewUrl: URL.createObjectURL(file) });
        }
      } finally {
        if (needsTranscode) setPreparing(false);
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

  // Resume a "review in background" run: if we arrived with a pending generation (the
  // user tapped "Tailor in the background" in the deck, or is returning to /add-photo)
  // and there's no fresh pick/handoff in flight, resurface the progress pill so the deck
  // is one tap away once it's ready. Runs BEFORE the handoff effect so it never competes
  // with a drawer hand-off (which owns the pristine-mount case).
  useEffect(() => {
    const pending = useGenerationStore.getState().pending;
    const hasHandoff = usePhotoPickStore.getState().files.length > 0;
    if (pending && !hasHandoff && pickedRef.current.length === 0) {
      setGenRun(pending);
      setStep('preparing');
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Drawer handoff: consume Files stashed by AddItemDrawer and go straight to detect
  // (transcoding any HEIC first, inside addFiles).
  useEffect(() => {
    const handoff = usePhotoPickStore.getState().takeFiles();
    if (handoff.length === 0) return;
    void (async () => {
      const list = await addFiles(handoff);
      if (list.length > 0) await runDetect(list);
    })();
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
      const list = pickedRef.current;
      // Commit re-uploads only the files backing LIVE sessions — duplicates have no
      // session for the server to hash-match, so their bytes stay home.
      const liveFiles = list
        .filter((_, i) => sess[i] && !sess[i].duplicate && sess[i].session_id)
        .map((p) => p.file);
      // Show the "Tailoring your items" waiting screen INSTANTLY on tap — don't block it
      // behind the commit call. commitPhotoIngest cuts out + stages every region server-
      // side before it returns (~10s), which used to keep the RegionSelector on screen the
      // whole time. We now flip to 'preparing' first (genRun null → indeterminate waiting
      // copy) and run commit in the background; the progress pill fills in with the real
      // count once the run id comes back.
      // ⚠️ BACKEND: the ~10s is server-synchronous cutout in POST /photo/ingest/commit, so
      // the run id + item count can't appear until it returns. If we want the COUNT instant
      // too, commit must be split into a fast stage-ack + async cutout.
      setError(null);
      setNotice(null);
      setGenRun(null);
      setStep('preparing');
      try {
        const res = await commitPhotoIngest(liveFiles, selections);
        useClosetStore.getState().invalidate?.();
        if (res.staged > 0) {
          // Product cards are now generating in the background. Reset the picker and let
          // the non-blocking "Preparing N → Review" pill (already visible) take the count;
          // it routes to the run-scoped deck when the user chooses (or once it's ready).
          list.forEach((p) => URL.revokeObjectURL(p.previewUrl));
          updatePicked([]);
          setSessions(null);
          // Stash the run so the pill can resurface if the user navigates away (e.g. the
          // in-deck "Tailor in the background" escape) and needs pulling back when ready.
          useGenerationStore.getState().setPending({ syncId: res.sync_id, staged: res.staged });
          setGenRun({ syncId: res.sync_id, staged: res.staged });
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
    [sessions, runDetect, updatePicked],
  );

  const busy = step === 'detecting' || step === 'committing' || preparing;

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

      {preparing && (
        <div
          className="flex items-center gap-2.5 rounded-lg px-3 py-2 text-[13px]"
          style={{ background: 'var(--tr-10)', color: 'rgba(255,255,255,0.75)' }}
          role="status"
        >
          <span
            className="h-4 w-4 shrink-0 rounded-full"
            style={{
              border: '2px solid var(--tr-20)',
              borderTopColor: 'var(--mint)',
              animation: 'tailor-spin 0.8s linear infinite',
            }}
          />
          Preparing photo… converting HEIC for upload.
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

      {step === 'preparing' && (
        <div className="flex flex-1 flex-col items-center justify-center gap-6 py-12 text-center">
          <div className="flex flex-col items-center gap-2">
            <span style={{ fontSize: 34 }}>✨</span>
            <p className="m-0 text-[16px] font-semibold text-white">Tailoring your items</p>
            <p className="mt-1 max-w-[260px] text-[13px]" style={{ color: 'rgba(255,255,255,0.55)' }}>
              We&rsquo;re pressing clean product shots. Wait here and your review opens
              the moment they&rsquo;re ready.
            </p>
          </div>
          {genRun ? (
            // Commit returned → the real progress pill. Waiting here auto-advances to the
            // deck when the run finishes (no tap). Tapping early still works; onReview
            // clears the stashed run.
            <GenerationProgressPill
              syncId={genRun.syncId}
              staged={genRun.staged}
              onReview={() => useGenerationStore.getState().clear()}
              onDone={() => {
                useGenerationStore.getState().clear();
                router.push(`/review?sync_id=${encodeURIComponent(genRun.syncId)}`);
              }}
            />
          ) : (
            // Commit still in flight (server-side cutout) — indeterminate spinner so the
            // waiting screen is up instantly instead of blocking on the RegionSelector.
            <div
              className="inline-flex items-center gap-2.5 rounded-full"
              style={{ background: 'var(--tr-10)', border: '1px solid var(--tr-20)', padding: '11px 18px' }}
              role="status"
              aria-label="Preparing your items"
            >
              <span
                className="h-4 w-4 shrink-0 rounded-full"
                style={{
                  border: '2px solid var(--tr-20)',
                  borderTopColor: 'var(--mint)',
                  animation: 'tailor-spin 0.8s linear infinite',
                }}
                aria-hidden
              />
              <span className="text-[14px] font-semibold" style={{ color: 'rgba(255,255,255,0.85)' }}>
                Preparing your items…
              </span>
            </div>
          )}
          <button
            type="button"
            onClick={() => router.push('/home')}
            className="text-[13px] underline"
            style={{ color: 'rgba(255,255,255,0.5)' }}
          >
            Tailor in the background
          </button>
        </div>
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
              // Snapshot into a REAL, DETACHED array as the very first line — before
              // any state update or reset. e.target.files is a LIVE FileList tied to
              // the input element: resetting e.currentTarget.value clears that SAME
              // FileList in place, so reading it after the reset (or after any await)
              // sees length 0. Array.from() copies it out while it's still live.
              const fileArray = Array.from(e.target.files ?? []);
              e.currentTarget.value = ''; // safe now — snapshot already taken
              void addFiles(fileArray);
            }}
          />
          <input
            ref={cameraRef}
            type="file"
            accept="image/*"
            capture="environment"
            className="hidden"
            onChange={(e) => {
              // Same snapshot-before-reset fix as the gallery input above.
              const fileArray = Array.from(e.target.files ?? []);
              e.currentTarget.value = ''; // safe now — snapshot already taken
              void addFiles(fileArray);
            }}
          />

          {/* Intentional entry: two big, tappable source cards (icon + title + sub)
              instead of flat buttons — the redesigned /add-photo landing. */}
          <div className="grid grid-cols-2 gap-3">
            <button
              type="button"
              onClick={() => cameraRef.current?.click()}
              disabled={busy}
              className="group flex flex-col items-center gap-2.5 rounded-2xl px-4 py-6 text-center transition-transform active:scale-[0.98] disabled:opacity-50"
              style={{ background: 'var(--tr-10)', border: '1px solid var(--tr-20)' }}
            >
              <span
                className="flex items-center justify-center rounded-full"
                style={{ width: 52, height: 52, background: 'var(--mint)', color: 'var(--brand-teal)' }}
              >
                <Camera size={24} />
              </span>
              <span className="text-[15px] font-semibold text-white">Take photo</span>
              <span className="text-[12.5px]" style={{ color: 'rgba(255,255,255,0.55)' }}>
                Use your camera
              </span>
            </button>
            <button
              type="button"
              onClick={() => galleryRef.current?.click()}
              disabled={busy}
              className="group flex flex-col items-center gap-2.5 rounded-2xl px-4 py-6 text-center transition-transform active:scale-[0.98] disabled:opacity-50"
              style={{ background: 'var(--tr-10)', border: '1px solid var(--tr-20)' }}
            >
              <span
                className="flex items-center justify-center rounded-full"
                style={{ width: 52, height: 52, background: 'var(--tr-20)', color: 'white' }}
              >
                <ImagePlus size={24} />
              </span>
              <span className="text-[15px] font-semibold text-white">Choose photos</span>
              <span className="text-[12.5px]" style={{ color: 'rgba(255,255,255,0.55)' }}>
                From your library
              </span>
            </button>
          </div>

          {picked.length === 0 ? (
            // Nothing picked yet — a quiet guidance line (the source cards are the CTA).
            <p className="mt-1 text-center text-[12.5px]" style={{ color: 'rgba(255,255,255,0.5)' }}>
              Use a photo of just yourself — we&rsquo;ll spot each garment. JPEG, PNG, WebP,
              or HEIC, up to {MAX_FILE_SIZE / 1024 / 1024}MB each.
            </p>
          ) : (
            <>
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

              <button
                type="button"
                onClick={handleSubmit}
                disabled={busy}
                className="rounded-xl py-3.5 text-[15px] font-semibold disabled:opacity-50"
                style={{ background: 'var(--mint)', color: 'var(--brand-teal)' }}
              >
                {`Find clothes in ${picked.length} photo${picked.length > 1 ? 's' : ''}`}
              </button>
            </>
          )}
        </>
      )}
    </div>
  );
}
