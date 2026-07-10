'use client';

/**
 * PhotoIngestUpload — photo → closet ingestion, Wave 1.5 (detect → select → commit).
 *
 * The old one-shot upload auto-staged every detected garment. Now it's a small
 * state machine:
 *   pick       — choose/capture up to 10 photos (client-side validation + previews);
 *   detecting  — POST /photo/ingest/detect finds garment regions per photo;
 *   select     — RegionSelector: toggle detected regions on/off, draw missed ones;
 *   preparing  — Add tapped: POST /photo/ingest/commit re-uploads the SAME File objects
 *                (the server re-matches them by content hash) + the selections in the
 *                background while a lightweight spinner shows. The MOMENT it stages we
 *                route to the /review swipe deck scoped to the new run — product-image
 *                generation is a background job and the deck streams cards in, so the tap
 *                never blocks on generation.
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
import {
  Btn,
  M,
  PermissionState,
  ThinkingScreen,
  Thinking,
} from '@/components/ds';
import { RegionSelector } from './RegionSelector';
import { GenerationProgressPill } from './GenerationProgressPill';

// 'preparing' = Add was tapped; the commit (server-side cutout) is running. As soon as it
// stages we route STRAIGHT to the run-scoped review deck — product-image generation is a
// background job (photo_generation / self-heal) and the deck streams each card in as it's
// verified, so the tap never blocks on generation. genRun is only set on the resume path
// (returning to /add-photo with a run still generating), which shows the progress pill.
type Step = 'pick' | 'detecting' | 'select' | 'preparing';

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

// Drop a PROVISIONAL background indicator (one set with no sync_id while a commit was
// still in flight). Real runs (syncId set) are left alone.
function clearProvisionalPending() {
  const p = useGenerationStore.getState().pending;
  if (p && p.syncId == null) useGenerationStore.getState().clear();
}

// ── I3 · Detecting — the real photo full-bleed with a mint scan line ──────────
// Shows the ACTUAL uploaded photo being scanned (object URL), a deep-glass "Finding your
// clothes…" pill with the Thinking mark, and a moving scan line (t2-scan). When several
// photos were picked, `index`/`total` drive the "N of M" the caller mirrors into the
// TopBar, and the visible photo switches as detection advances across them.
function DetectingScreen({
  photos,
  index,
  onCancel,
}: {
  photos: { previewUrl: string }[];
  index: number;
  onCancel: () => void;
}) {
  const current = photos[Math.min(index, photos.length - 1)];
  return (
    <div className="relative flex min-h-0 flex-1 flex-col">
      <div
        className="relative min-h-0 flex-1 overflow-hidden"
        style={{ borderRadius: 28, border: '1px solid rgba(255,255,255,0.14)', minHeight: 320 }}
      >
        {current && (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={current.previewUrl}
            alt=""
            className="absolute inset-0 h-full w-full object-cover"
            style={{ filter: 'brightness(0.85)' }}
          />
        )}
        {/* Mint scan line — CSS t2-scan sweeps top 14%→84%. */}
        <span
          data-t2-anim
          aria-hidden
          className="absolute"
          style={{
            left: 10,
            right: 10,
            height: 2,
            borderRadius: 1,
            background: 'linear-gradient(90deg, transparent, var(--mint), transparent)',
            boxShadow: '0 0 18px rgba(75,226,214,0.8)',
            animation: 't2-scan 3s var(--ease-in-out) infinite',
          }}
        />
        <div
          className="pointer-events-none absolute inset-0"
          style={{ background: 'linear-gradient(to top, rgba(0,0,0,0.55), transparent 40%)' }}
          aria-hidden
        />
        <div className="absolute inset-x-0 flex justify-center" style={{ bottom: 18 }}>
          <div
            className="flex items-center"
            style={{ ...M.deep(999), gap: 10, padding: '9px 18px 9px 10px' }}
            role="status"
          >
            <Thinking size={28} />
            <span className="text-white" style={{ fontSize: 13, fontWeight: 600 }}>
              Finding your clothes…
            </span>
          </div>
        </div>
      </div>
      <p className="mt-3 text-center text-[12.5px]" style={{ color: M.faint }}>
        Usually under 10 seconds 
      </p>
      <div className="mt-2">
        <Btn variant="ghost" size="md" fullWidth onClick={onCancel}>
          Cancel
        </Btn>
      </div>
    </div>
  );
}

/** Amber-tinted inline banner (offline/notice tone) used for the transcode + notice rows. */
function InfoRow({ children, role }: { children: React.ReactNode; role?: string }) {
  return (
    <div
      className="flex items-center gap-2.5"
      style={{
        padding: '11px 14px',
        borderRadius: 15,
        background: 'rgba(255,255,255,0.08)',
        border: '1px solid rgba(255,255,255,0.14)',
        backdropFilter: 'blur(12px)',
        WebkitBackdropFilter: 'blur(12px)',
      }}
      role={role}
    >
      <span style={{ flex: 1, color: '#fff', fontSize: 12.8, lineHeight: 1.45 }}>{children}</span>
    </div>
  );
}

export interface PhotoIngestUploadProps {
  /** Reports the current pipeline phase + counts so the page can mirror "N of M" into the
   *  TopBar sub. Fires on step/index changes; null when there is nothing to show. */
  onPhaseChange?: (
    phase: { step: Step; index: number; total: number } | null,
  ) => void;
}

export function PhotoIngestUpload({ onPhaseChange }: PhotoIngestUploadProps = {}) {
  const router = useRouter();
  const [picked, setPicked] = useState<Picked[]>([]);
  const [step, setStep] = useState<Step>('pick');
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  // Camera/photo access refused — surfaces the §0 PermissionState template. Cleared when
  // the user retries. Never blocks the file inputs beyond the tap that hit the denial.
  const [permissionDenied, setPermissionDenied] = useState<'camera' | 'photos' | null>(null);
  // Resume path only: returning to /add-photo with a run still generating shows the
  // "Preparing N → Review" progress pill. The commit flow never sets this — it routes
  // straight to the review deck as soon as the commit stages.
  const [genRun, setGenRun] = useState<{ syncId: string; staged: number } | null>(null);
  // True while a HEIC/HEIF file is being transcoded to JPEG (async, can be slow on
  // large photos) — drives a lightweight "preparing" affordance so the UI isn't frozen.
  const [preparing, setPreparing] = useState(false);
  // Detect sessions, index-aligned with `picked` (the API returns them in file order).
  const [sessions, setSessions] = useState<PhotoDetectSession[] | null>(null);
  // Which picked photo the detecting screen is visibly scanning (0-based). Advances
  // presentationally across photos while the single detect call is in flight — the real
  // call is one request; this just paces the "N of M" so multi-photo scans read honestly.
  const [detectIndex, setDetectIndex] = useState(0);
  // Estimated staged count for the in-flight commit — the number the provisional
  // background indicator shows before commit returns the real sync_id + count.
  const stagedGuessRef = useRef(0);
  // Set when the user taps "Tailor in the background" WHILE the commit is still running.
  // A commit that resolves after this must NOT yank the user (now on /home) into the deck —
  // it only patches the real sync_id onto the pending run so the global notice recovers it.
  const backgroundedRef = useRef(false);
  // Set when the user taps Cancel on the detecting screen. The detect call can't be
  // aborted mid-flight, so runDetect checks this after it resolves and bails instead of
  // advancing to 'select'.
  const detectCancelledRef = useRef(false);

  const galleryRef = useRef<HTMLInputElement>(null);
  const cameraRef = useRef<HTMLInputElement>(null);

  // Ref mirror of `picked` so async handlers + the unmount cleanup never see a
  // stale list (and previews are always revocable exactly once each).
  const pickedRef = useRef<Picked[]>([]);
  const updatePicked = useCallback((next: Picked[]) => {
    pickedRef.current = next;
    setPicked(next);
  }, []);

  // NOTE: do NOT revoke preview object-URLs in a []-deps unmount cleanup. In the
  // drawer-handoff path `addFiles` runs synchronously (no await before
  // createObjectURL for non-HEIC), so pickedRef is populated *before* React 18
  // StrictMode's dev-only mount→unmount→remount probe fires — and a []-cleanup
  // would then revoke the blob the zone-selector still needs to render, while the
  // remount can't recreate it (the handoff store was already consumed). That
  // produced a dead blob URL (naturalWidth 0 / ERR_FILE_NOT_FOUND) behind the
  // detection boxes. Every intentional exit already revokes: removeAt(),
  // all-duplicate, commit-success, commit-nothing, and discard. A mid-flow
  // abandon (navigating away without acting) leaves a couple of preview blobs
  // that the browser reclaims when the document/tab unloads — an acceptable,
  // bounded trade for a preview that actually renders.

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

  // Open a source picker, first checking a queryable camera permission so a hard denial
  // surfaces the PermissionState template instead of silently opening a picker that can't
  // capture. `photos` has no standard permission API, so its picker always opens; if the
  // OS sheet is dismissed with no file the flow simply stays on 'pick'.
  const openSource = useCallback(async (source: 'camera' | 'photos') => {
    setPermissionDenied(null);
    if (source === 'camera' && typeof navigator !== 'undefined' && navigator.permissions?.query) {
      try {
        // 'camera' isn't in every lib's PermissionName union — cast narrowly.
        const st = await navigator.permissions.query({
          name: 'camera' as PermissionName,
        });
        if (st.state === 'denied') {
          setPermissionDenied('camera');
          return;
        }
      } catch {
        /* Permissions API unavailable/unsupported for 'camera' — fall through and open. */
      }
    }
    (source === 'camera' ? cameraRef : galleryRef).current?.click();
  }, []);

  /** Run detection on `list`. Doesn't clear `notice` — callers set/keep it (the
   *  410 auto-rescan shows its notice THROUGH the detecting spinner). */
  const runDetect = useCallback(
    async (list: Picked[]) => {
      if (list.length === 0) return;
      setStep('detecting');
      setError(null);
      setSessions(null);
      setDetectIndex(0);
      detectCancelledRef.current = false;
      // Pace the "N of M" across the picked photos while the single detect call runs. The
      // request is one round-trip; this timer only advances which photo is visibly scanning
      // so a multi-photo batch reads as progressing (it stops at the last photo).
      const paceTimers: ReturnType<typeof setTimeout>[] = [];
      if (list.length > 1) {
        for (let i = 1; i < list.length; i++) {
          paceTimers.push(setTimeout(() => setDetectIndex(i), i * 1100));
        }
      }
      try {
        const res = await detectPhotoIngest(list.map((p) => p.file));
        paceTimers.forEach(clearTimeout);
        if (detectCancelledRef.current) return; // user tapped Cancel mid-scan — already on 'pick'
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
        paceTimers.forEach(clearTimeout);
        if (detectCancelledRef.current) return; // cancelled — don't surface an error on 'pick'
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
    // Only resume a REAL run (has a sync_id) into the preparing pill — a provisional
    // pending (no id yet) has nothing to poll here.
    if (pending?.syncId && !hasHandoff && pickedRef.current.length === 0) {
      setGenRun({ syncId: pending.syncId, staged: pending.staged });
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

  const handleCancelDetect = useCallback(() => {
    // Abandon an in-flight scan: flag it so runDetect bails when the request resolves,
    // then drop back to pick with the files intact for a retry.
    detectCancelledRef.current = true;
    setDetectIndex(0);
    setStep('pick');
  }, []);

  // Mirror the pipeline phase (+ "N of M" during detection) up to the host page so it can
  // reflect scan progress in the TopBar sub. Cleared (null) outside the detecting step.
  useEffect(() => {
    if (!onPhaseChange) return;
    if (step === 'detecting') {
      onPhaseChange({ step, index: detectIndex, total: picked.length });
    } else {
      onPhaseChange(null);
    }
  }, [onPhaseChange, step, detectIndex, picked.length]);

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
      // Estimate the staged count now (selected regions + manual boxes) so a provisional
      // background indicator can show a number instantly if the user backgrounds the flow
      // before commit returns.
      stagedGuessRef.current = selections.reduce(
        (n, s) => n + s.selected_region_ids.length + s.manual_boxes.length,
        0,
      );
      setError(null);
      setNotice(null);
      setGenRun(null);
      backgroundedRef.current = false;
      // Leave the RegionSelector the INSTANT Add is tapped — flip to the lightweight
      // "Preparing…" screen (genRun null → indeterminate spinner + a "Tailor in the
      // background" escape) and run the commit in the background. commitPhotoIngest cuts out
      // + stages every region server-side (~10s) before it returns the run id.
      setStep('preparing');

      try {
        const res = await commitPhotoIngest(liveFiles, selections);
        useClosetStore.getState().invalidate?.();
        if (res.staged > 0) {
          list.forEach((p) => URL.revokeObjectURL(p.previewUrl));
          updatePicked([]);
          setSessions(null);
          // Stash the run so the global "review in background" notice can recover it if the
          // user leaves the deck before confirming; the deck clears it on confirm. This also
          // patches the real sync_id over any provisional pending set by backgrounding.
          useGenerationStore.getState().setPending({ syncId: res.sync_id, staged: res.staged });
          // If the user already tapped "Tailor in the background" they're on /home now —
          // don't yank them back; the global notice carries the (now real) run.
          if (backgroundedRef.current) return;
          // READY-FIRST (Photo-seam Phase 3): do NOT route into the deck yet — stay on
          // the progress screen. GenerationProgressPill polls the run and auto-advances
          // to /review only when the WHOLE batch settles (every item's card ready or
          // terminally failed) — the review never opens on a half-tailored batch.
          setGenRun({ syncId: res.sync_id, staged: res.staged });
          return;
        }
        // Nothing staged — surface why and reset to pick. Drop any provisional background
        // indicator the user set by backgrounding (it has no real run to point to).
        clearProvisionalPending();
        list.forEach((p) => URL.revokeObjectURL(p.previewUrl));
        updatePicked([]);
        setSessions(null);
        setStep('pick');
        setNotice(res.message ?? 'No new items to review.');
      } catch (err) {
        if (err instanceof PhotoSessionExpiredError) {
          // Detect sessions TTL'd out server-side — transparently re-scan the same
          // files. (Selections reset to all-selected: region ids may change.)
          clearProvisionalPending();
          setNotice('That scan expired — re-scanning your photos…');
          await runDetect(list);
          return;
        }
        // Commit failed — a provisional background indicator would point at nothing, clear
        // it. Back to the selector with the files intact so Add can be retried.
        clearProvisionalPending();
        setStep('select');
        setError(err instanceof Error ? err.message : 'Failed to add items.');
      }
    },
    [sessions, runDetect, updatePicked, router],
  );

  const busy = step === 'detecting' || preparing;

  // ── Permission denied — full-panel §0 template (camera or photos). ─────────
  if (permissionDenied) {
    return (
      <div className="flex min-h-0 flex-1 items-center justify-center">
        <PermissionState
          kind={permissionDenied}
          onSecondary={() => setPermissionDenied(null)}
        />
      </div>
    );
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-4">
      {error && (
        <div
          className="flex items-center gap-2.5"
          style={{
            padding: '11px 14px',
            borderRadius: 15,
            background: 'rgba(251,44,54,0.13)',
            border: '1px solid rgba(251,44,54,0.32)',
            backdropFilter: 'blur(12px)',
            WebkitBackdropFilter: 'blur(12px)',
          }}
          role="alert"
        >
          <span style={{ flex: 1, color: '#fff', fontSize: 12.8, lineHeight: 1.45 }}>{error}</span>
        </div>
      )}
      {notice && <InfoRow>{notice}</InfoRow>}

      {preparing && (
        <InfoRow role="status">
          <span className="inline-flex items-center gap-2.5">
            <span
              className="inline-block h-4 w-4 shrink-0 rounded-full align-middle"
              style={{
                border: '2px solid var(--tr-20)',
                borderTopColor: 'var(--mint)',
                animation: 'tailor-spin 0.8s linear infinite',
              }}
            />
            Preparing photo… converting HEIC for upload.
          </span>
        </InfoRow>
      )}

      {step === 'detecting' && (
        <DetectingScreen photos={picked} index={detectIndex} onCancel={handleCancelDetect} />
      )}

      {step === 'select' && sessions && (
        <RegionSelector
          photos={picked.map((p, i) => ({ previewUrl: p.previewUrl, session: sessions[i] }))}
          onCancel={handleCancelSelect}
          onCommit={handleCommit}
        />
      )}

      {step === 'preparing' && (
        <div className="flex flex-1 flex-col items-center justify-center gap-6 py-6 text-center">
          <ThinkingScreen
            title="Tailoring your items"
            sub="We&rsquo;re pressing clean product shots. Wait here and your review opens the moment they&rsquo;re ready."
          />
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
              <span className="text-[14px] font-semibold" style={{ color: M.soft }}>
                Preparing your items…
              </span>
            </div>
          )}
          <button
            type="button"
            onClick={() => {
              // Mark backgrounded so a commit that resolves after this leaves the user on
              // /home (it only patches the real sync_id onto the pending run) instead of
              // routing them into the deck.
              backgroundedRef.current = true;
              // If commit hasn't returned a run yet, drop a PROVISIONAL pending so the home
              // indicator shows INSTANTLY (not after commit finishes ~10s later). It's
              // patched to the real sync_id the moment commit resolves.
              if (!useGenerationStore.getState().pending) {
                useGenerationStore.getState().setPending({ syncId: null, staged: stagedGuessRef.current });
              }
              router.push('/home');
            }}
            className="text-[13px] underline"
            style={{ color: M.faint }}
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

          {/* Intentional entry: two big, tappable source cards (icon medallion + title +
              sub) — the redesigned /add-photo landing. */}
          <div className="grid grid-cols-2 gap-3">
            <button
              type="button"
              onClick={() => void openSource('camera')}
              disabled={busy}
              className="flex flex-col items-center gap-2.5 px-4 py-6 text-center transition-transform active:scale-[0.98] disabled:opacity-50"
              style={{ borderRadius: 20, background: 'rgba(255,255,255,0.07)', border: '1px solid rgba(255,255,255,0.11)' }}
            >
              <span
                className="flex items-center justify-center text-white"
                style={{
                  width: 52,
                  height: 52,
                  borderRadius: 17,
                  background: 'linear-gradient(165deg, #10635c, #0a3633)',
                  border: '1px solid rgba(255,255,255,0.16)',
                }}
              >
                <Camera size={24} />
              </span>
              <span className="text-[15px] font-semibold text-white">Snap a photo</span>
              <span className="text-[12.5px]" style={{ color: M.faint }}>
                Use your camera
              </span>
            </button>
            <button
              type="button"
              onClick={() => void openSource('photos')}
              disabled={busy}
              className="flex flex-col items-center gap-2.5 px-4 py-6 text-center transition-transform active:scale-[0.98] disabled:opacity-50"
              style={{ borderRadius: 20, background: 'rgba(255,255,255,0.07)', border: '1px solid rgba(255,255,255,0.11)' }}
            >
              <span
                className="flex items-center justify-center text-white"
                style={{ width: 52, height: 52, borderRadius: 17, background: 'rgba(255,255,255,0.1)', border: '1px solid rgba(255,255,255,0.16)' }}
              >
                <ImagePlus size={24} />
              </span>
              <span className="text-[15px] font-semibold text-white">Choose photos</span>
              <span className="text-[12.5px]" style={{ color: M.faint }}>
                From your library
              </span>
            </button>
          </div>

          {picked.length === 0 ? (
            // Nothing picked yet — a quiet guidance line (the source cards are the CTA).
            <p className="mt-1 text-center text-[12.5px]" style={{ color: M.faint }}>
              Use a photo of just yourself — we&rsquo;ll spot each garment. JPEG, PNG, WebP,
              or HEIC, up to {MAX_FILE_SIZE / 1024 / 1024}MB each.
            </p>
          ) : (
            <>
              <div className="grid grid-cols-3 gap-2">
                {picked.map((p, i) => (
                  <div
                    key={p.id}
                    className="relative aspect-square overflow-hidden"
                    style={{ borderRadius: 16, background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.09)' }}
                  >
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img src={p.previewUrl} alt={`Selected ${i + 1}`} className="h-full w-full object-cover" />
                    <button
                      type="button"
                      onClick={() => removeAt(i)}
                      aria-label="Remove"
                      className="absolute right-1.5 top-1.5 flex h-6 w-6 items-center justify-center rounded-full"
                      style={{ background: 'rgba(0,0,0,0.55)', border: '1px solid rgba(255,255,255,0.18)', color: 'white', backdropFilter: 'blur(8px)' }}
                    >
                      <X size={13} />
                    </button>
                  </div>
                ))}
              </div>

              <Btn variant="mint" size="lg" fullWidth onClick={handleSubmit} disabled={busy}>
                {`Find clothes in ${picked.length} photo${picked.length > 1 ? 's' : ''}`}
              </Btn>
            </>
          )}
        </>
      )}
    </div>
  );
}
