'use client';

/**
 * /review — Gmail receipt swipe-review deck (variation A, decision-first).
 *
 * Loads pending ingest candidates, lets the user accept / reject / edit each one
 * via a card deck, then confirms the batch into the closet. Replaces the old
 * /gmail-sync flow; wired to the real ingest candidates + confirm endpoints.
 */

import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import { Camera, Check, Mail, Pencil, Sparkles, X } from 'lucide-react';

import { useRequireAuth } from '@/lib/auth/useRequireAuth';
import { useClosetStore } from '@/stores/useClosetStore';
import { useGenerationStore } from '@/stores/useGenerationStore';
import {
  confirmCandidates,
  fetchGmailConnectionStatus,
  getIngestCandidates,
  getIngestStatus,
  startGmailConnect,
  startIngest,
  type ConfirmResponse,
  type IngestCandidate,
} from '@/lib/api/gmail';
import { AppShell } from '@/components/layout/AppShell';
import { ItemImage } from '@/components/ui/ItemImage';
import { ConfidenceDot } from '@/components/ui/ConfidenceDot';
import { LightButton } from '@/components/ui/LightButton';
import { EmptyState } from '@/components/ui/EmptyState';

type CardEdits = Record<string, Record<string, unknown>>;

// A bordered "Label Value" pill (Option A). Label muted, value bold. Only rendered by
// the caller when the value exists — never a blank/empty chip.
function FactChip({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <span
      className="inline-flex items-center gap-1"
      style={{
        background: 'var(--tr-10)',
        border: '1px solid var(--tr-20)',
        borderRadius: 10,
        padding: '7px 11px',
      }}
    >
      <span style={{ color: 'rgba(255,255,255,0.5)', fontSize: 11 }}>{label}</span>
      <span className="font-semibold text-white" style={{ fontSize: 13 }}>{value}</span>
    </span>
  );
}

export default function ReviewPage() {
  const router = useRouter();
  const { status } = useRequireAuth();
  const isAuth = status === 'authenticated';

  const [candidates, setCandidates] = useState<IngestCandidate[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [index, setIndex] = useState(0);
  const [accepted, setAccepted] = useState<string[]>([]);
  const [rejected, setRejected] = useState<string[]>([]);
  const [edits, setEdits] = useState<CardEdits>({});

  // Inline editor state for the current card.
  const [editing, setEditing] = useState(false);

  // Drag-to-swipe state for the top card. `x` is the live horizontal offset (px);
  // `dragging` disables the snap-back transition while the finger/mouse is down.
  const [drag, setDrag] = useState<{ x: number; dragging: boolean }>({ x: 0, dragging: false });
  const dragStartRef = useRef<number | null>(null); // pointer clientX at press
  const dragXRef = useRef(0);                        // live offset (read on release, no stale closure)

  const [confirming, setConfirming] = useState(false);
  const [confirmError, setConfirmError] = useState<string | null>(null);
  const [result, setResult] = useState<ConfirmResponse | null>(null);

  // Progressive sync state. A sync is started ONLY by the explicit "Scan my inbox" CTA
  // (handleScan below) — never automatically on mount, focus, or poll — so visiting an
  // empty deck can never silently fire a billable extraction run.
  const [scanning, setScanning] = useState(false);   // a sync is running; deck streams
  const [scanCount, setScanCount] = useState(0);
  const [starting, setStarting] = useState(false);   // CTA tapped, startIngest in flight
  const [scanError, setScanError] = useState<string | null>(null);
  // Gmail connection (drives the "Connect Gmail to begin" empty state).
  const [gmailConnected, setGmailConnected] = useState<boolean | null>(null);
  const [connectBusy, setConnectBusy] = useState(false);

  // Wave 2: true while a photo run is still generating product cards (run status
  // 'running'). Covers the brief window after commit where a photo candidate is still
  // generation_status=null but its card is being made — so the deck shows a "creating…"
  // state instead of flashing the raw crop. Only meaningful for a sync-scoped photo deck.
  const [runGenerating, setRunGenerating] = useState(false);

  const mountedRef = useRef(true);
  // When the deck is opened for a specific run (the photo flow navigates to
  // /review?sync_id=…), scope every candidate fetch to that run so stale pending
  // candidates from earlier runs never appear. undefined = Gmail deck (all pending).
  // Read from window.location (not useSearchParams) to avoid the Suspense requirement.
  const scopeSyncIdRef = useRef<string | undefined>(undefined);
  const timersRef = useRef<ReturnType<typeof setTimeout>[]>([]);
  const schedule = useCallback((fn: () => void, ms: number) => {
    timersRef.current.push(setTimeout(fn, ms));
  }, []);

  // Merge a freshly-polled candidate list into the deck WITHOUT disrupting the user's
  // position: update image fields on cards already shown (no reorder, no remount), and
  // APPEND newly-staged cards in arrival order. Returns the same ref when nothing
  // changed so the deck doesn't needlessly re-render.
  const mergeCandidates = useCallback((incoming: IngestCandidate[]) => {
    setCandidates((prev) => {
      const seen = new Set(prev.map((c) => c.candidate_id));
      const incomingById = new Map(incoming.map((c) => [c.candidate_id, c]));
      let changed = false;
      const updated = prev.map((c) => {
        const u = incomingById.get(c.candidate_id);
        // Refresh in place (same index → deck position kept) whenever the server has
        // enriched ANY displayed field — not just the image. Cards staged early can
        // gain name/brand/category/color/size/price/confidence as a second contributing
        // email merges (backend COALESCE), and images stream in from the background
        // fill. User edits live separately in `edits`, so replacing the candidate row
        // never clobbers an in-flight edit.
        if (
          u &&
          (u.image_url !== c.image_url ||
            u.image_status !== c.image_status ||
            u.generated_image_url !== c.generated_image_url ||
            u.generation_status !== c.generation_status ||
            u.name !== c.name ||
            u.brand !== c.brand ||
            u.category !== c.category ||
            u.color !== c.color ||
            u.size !== c.size ||
            u.unit_price !== c.unit_price ||
            u.currency !== c.currency ||
            u.confidence_overall !== c.confidence_overall)
        ) {
          changed = true;
          return u;
        }
        return c;
      });
      const fresh = incoming.filter((c) => !seen.has(c.candidate_id));
      if (fresh.length === 0 && !changed) return prev;
      return [...updated, ...fresh];
    });
  }, []);

  // While images keep resolving OR a photo run keeps generating product cards, poll to
  // swap them in. READ-only — never starts a sync. For a sync-scoped photo deck it also
  // reads the run status, so the "creating…" state persists across the window where a
  // candidate is still generation_status=null but the run is mid-generation.
  const pollImages = useCallback(async function pollImages() {
    if (!mountedRef.current) return;
    try {
      const syncId = scopeSyncIdRef.current;
      const [cands, st] = await Promise.all([
        getIngestCandidates(syncId),
        // Status only matters when scoped to a run (the photo flow); tolerate its failure.
        syncId ? getIngestStatus(syncId).catch(() => null) : Promise.resolve(null),
      ]);
      if (!mountedRef.current) return;
      mergeCandidates(cands);
      const generating = st ? st.status === 'running' : false;
      setRunGenerating(generating);
      const stillResolving = cands.some((c) => c.image_status === 'pending');
      const stillGenerating = generating || cands.some((c) => c.generation_status === 'generating');
      if (stillResolving || stillGenerating) schedule(pollImages, 2500);
    } catch {
      /* transient — a manual refresh recovers */
    }
  }, [mergeCandidates, schedule]);

  // While the sync runs, stream staged cards + keep the scanning count live. Reads
  // status/candidates only — it does NOT (re)start a sync.
  const pollSync = useCallback(async function pollSync(syncId: string) {
    if (!mountedRef.current) return;
    try {
      const [st, cands] = await Promise.all([
        getIngestStatus(syncId),
        getIngestCandidates(scopeSyncIdRef.current),
      ]);
      if (!mountedRef.current) return;
      mergeCandidates(cands);
      setScanCount(st.progress.extracted || cands.length);
      if (st.status === 'running') {
        schedule(() => pollSync(syncId), 1500);
      } else {
        setScanning(false); // extraction finished → clear the indicator
        pollImages();       // images may still stream in from the background fill
      }
    } catch {
      if (mountedRef.current) schedule(() => pollSync(syncId), 2500);
    }
  }, [mergeCandidates, schedule, pollImages]);

  // THE ONLY sync-start path: an explicit user tap. Guarded so a double-tap (or a
  // refresh-then-tap) can't launch a second run; the backend additionally 409-reuses a
  // running sync and returns its id, so we resume streaming instead of starting another.
  const handleScan = useCallback(async () => {
    if (starting || scanning) return;
    setStarting(true);
    setScanError(null);
    // A Gmail scan is unscoped (all pending) — drop any photo-run scope from the URL
    // so this scan's cards aren't filtered to a different run.
    scopeSyncIdRef.current = undefined;
    try {
      const { sync_id } = await startIngest(); // 409 → id of the already-running sync
      if (!mountedRef.current) return;
      setScanning(true);
      pollSync(sync_id);
    } catch (err) {
      if (mountedRef.current) {
        setScanError(err instanceof Error ? err.message : 'Could not start a scan. Please try again.');
      }
    } finally {
      if (mountedRef.current) setStarting(false);
    }
  }, [starting, scanning, pollSync]);

  // Mount: LOAD candidates only — NEVER start a sync here. If a prior sync's images are
  // still resolving, resume image polling (read-only; does not start a sync).
  useEffect(() => {
    if (!isAuth) return;
    mountedRef.current = true;
    // Scope this deck to a run if the URL carries one (the photo flow navigates to
    // /review?sync_id=…). Gmail opens /review with no param -> undefined -> all pending.
    scopeSyncIdRef.current =
      new URLSearchParams(window.location.search).get('sync_id') ?? undefined;
    setLoading(true);
    // Connection status is read-only context for the empty state — never a sync.
    fetchGmailConnectionStatus()
      .then((s) => mountedRef.current && setGmailConnected(s.connected))
      .catch(() => mountedRef.current && setGmailConnected(null));
    getIngestCandidates(scopeSyncIdRef.current)
      .then((cands) => {
        if (!mountedRef.current) return;
        setCandidates(cands);
        setLoading(false);
        // Poll when images are still resolving, a card is generating, OR this is a
        // sync-scoped photo deck (one poll reads the run status; it self-stops once the
        // run is done and nothing is pending/generating).
        if (
          scopeSyncIdRef.current ||
          cands.some((c) => c.image_status === 'pending' || c.generation_status === 'generating')
        ) {
          pollImages();
        }
      })
      .catch((err) => {
        if (!mountedRef.current) return;
        setLoadError(err instanceof Error ? err.message : 'Failed to load candidates.');
        setLoading(false);
      });
    return () => {
      mountedRef.current = false;
      timersRef.current.forEach(clearTimeout);
      timersRef.current = [];
    };
  }, [isAuth, pollImages]);

  // Preload the NEXT couple of card images so they paint instantly on advance instead
  // of loading after the swipe (the "old image lingers ~2s" gap). `new Image()` warms
  // the browser's HTTP cache; the visible <img> then decodes from cache immediately.
  useEffect(() => {
    if (typeof window === 'undefined') return;
    for (let i = index + 1; i <= index + 2; i++) {
      const c = candidates[i];
      // Warm the image the card will actually show: the generated card once ready, else
      // the crop. (A still-generating card has nothing to preload.)
      const url =
        c?.generation_status === 'ready' && c.generated_image_url
          ? c.generated_image_url
          : c?.image_url;
      if (url) {
        const img = new window.Image();
        img.src = url;
      }
    }
  }, [index, candidates]);

  const total = candidates.length;
  const current = candidates[index];

  function advance() {
    setEditing(false);
    setIndex((i) => i + 1);
  }

  function handleAccept() {
    if (!current) return;
    setAccepted((a) => [...a, current.candidate_id]);
    advance();
  }

  function handleReject() {
    if (!current) return;
    setRejected((r) => [...r, current.candidate_id]);
    advance();
  }

  function setEdit(field: string, value: string) {
    if (!current) return;
    setEdits((prev) => ({
      ...prev,
      [current.candidate_id]: { ...(prev[current.candidate_id] ?? {}), [field]: value },
    }));
  }

  async function handleConfirm() {
    setConfirming(true);
    setConfirmError(null);
    try {
      const res = await confirmCandidates({ accepted, rejected, edits });
      useClosetStore.getState().invalidate();
      // This run's batch is decided — drop any pending "review in background" pill.
      useGenerationStore.getState().clear();
      setResult(res);
      router.refresh();
    } catch (err) {
      setConfirmError(err instanceof Error ? err.message : 'Failed to add items.');
    } finally {
      setConfirming(false);
    }
  }

  // ── Render guards ──────────────────────────────────────────────────────────

  if (status === 'loading' || !isAuth) {
    return (
      <AppShell scroll={false}>
        <div />
      </AppShell>
    );
  }

  if (loading) {
    return (
      <AppShell scroll={false}>
        <div className="flex h-full items-center justify-center">
          <div
            className="h-8 w-8 rounded-full"
            style={{ border: '3px solid var(--tr-20)', borderTopColor: 'var(--mint)', animation: 'tailor-spin 0.8s linear infinite' }}
          />
        </div>
      </AppShell>
    );
  }

  if (loadError) {
    return (
      <AppShell scroll={false}>
        <div className="flex h-full flex-col items-center justify-center px-8 text-center">
          <h1 className="m-0 text-[20px] font-bold text-white">Couldn&rsquo;t load imports</h1>
          <p className="mt-2 mb-6 text-[14px]" style={{ color: 'rgba(255,255,255,0.6)' }}>
            {loadError}
          </p>
          <LightButton onClick={() => router.push('/home')} style={{ height: 48, padding: '0 26px' }}>
            Back to home
          </LightButton>
        </div>
      </AppShell>
    );
  }

  // Empty candidates — but if a sync is scanning, open the deck shell into a
  // lightweight "scanning…" state (cards stream in below as they stage).
  if (total === 0) {
    if (scanning) {
      return (
        <AppShell scroll={false}>
          <div className="flex h-full flex-col items-center justify-center px-8 text-center">
            <div
              className="h-9 w-9 rounded-full"
              style={{ border: '3px solid var(--tr-20)', borderTopColor: 'var(--mint)', animation: 'tailor-spin 0.8s linear infinite' }}
            />
            <h1 className="mt-5 m-0 text-[18px] font-bold text-white">Scanning your inbox…</h1>
            <p className="mt-2 text-[13.5px]" style={{ color: 'rgba(255,255,255,0.6)' }}>
              {scanCount > 0
                ? `${scanCount} found so far — first cards appear in a moment`
                : 'Finding clothing purchases in your receipts'}
            </p>
          </div>
        </AppShell>
      );
    }
    // Gmail not connected yet — the designed "Connect Gmail to begin" prompt.
    if (gmailConnected === false) {
      return (
        <AppShell scroll={false}>
          <div className="flex h-full flex-col items-center justify-center px-2">
            <EmptyState
              icon={
                <svg width="42" height="42" viewBox="0 0 24 24" fill="none" aria-hidden>
                  <rect x="2.5" y="5" width="19" height="14" rx="2" fill="rgba(255,255,255,0.9)" />
                  <path d="M3.5 6.5l8.5 6 8.5-6" stroke="#ea4335" strokeWidth="1.6" fill="none" />
                </svg>
              }
              title="Connect Gmail to begin"
              body="Tailor builds your closet from email receipts. Connect once and items appear automatically."
              ctaLabel={connectBusy ? 'Opening Google…' : 'Connect Gmail'}
              onCta={() => {
                if (connectBusy) return;
                setConnectBusy(true);
                startGmailConnect().catch(() => setConnectBusy(false));
              }}
            />
            <button
              type="button"
              onClick={() => router.push('/closet')}
              className="mt-3 text-[13px] underline"
              style={{ color: 'rgba(255,255,255,0.5)' }}
            >
              Back to closet
            </button>
          </div>
        </AppShell>
      );
    }
    return (
      <AppShell scroll={false}>
        <div className="flex h-full flex-col items-center justify-center px-2">
          <EmptyState
            icon={<span style={{ fontSize: 38, color: 'var(--mint)' }}>✦</span>}
            title="Nothing to review yet"
            body="Scan your Gmail receipts to find clothing purchases to review."
            ctaLabel={starting ? 'Starting…' : 'Scan my inbox'}
            ctaIcon={<Mail size={18} />}
            onCta={handleScan}
          />
          {scanError && (
            <p className="mt-4 max-w-[280px] text-center text-[13px]" style={{ color: 'var(--danger)' }}>
              {scanError}
            </p>
          )}
          <button
            type="button"
            onClick={() => router.push('/profile')}
            className="mt-3 text-[13px] underline"
            style={{ color: 'rgba(255,255,255,0.5)' }}
          >
            Manage Gmail connection
          </button>
        </div>
      </AppShell>
    );
  }

  // ── Summary state (deck exhausted) ─────────────────────────────────────────
  if (index >= total) {
    // Still scanning: the user has caught up to the live edge — wait for more cards to
    // stage rather than prematurely showing the confirm/summary.
    if (scanning) {
      return (
        <AppShell scroll={false}>
          <div className="flex h-full flex-col items-center justify-center px-8 text-center">
            <div
              className="h-9 w-9 rounded-full"
              style={{ border: '3px solid var(--tr-20)', borderTopColor: 'var(--mint)', animation: 'tailor-spin 0.8s linear infinite' }}
            />
            <h1 className="mt-5 m-0 text-[18px] font-bold text-white">Scanning for more…</h1>
            <p className="mt-2 text-[13.5px]" style={{ color: 'rgba(255,255,255,0.6)' }}>
              You&rsquo;re all caught up — new items appear as we find them.
            </p>
          </div>
        </AppShell>
      );
    }
    return (
      <AppShell scroll={false}>
        <div className="flex h-full flex-col items-center justify-center px-8 text-center">
          {result ? (
            <>
              <div
                className="mb-5 flex items-center justify-center"
                style={{
                  width: 72,
                  height: 72,
                  borderRadius: '50%',
                  background: 'rgba(10,207,131,0.18)',
                  border: '1px solid rgba(10,207,131,0.4)',
                }}
              >
                <Check size={32} color="var(--success)" />
              </div>
              <h1 className="m-0 text-[22px] font-bold text-white">
                Added {result.inserted_count} to closet
              </h1>
              <p className="mt-2 mb-7 text-[14px]" style={{ color: 'rgba(255,255,255,0.6)' }}>
                {result.inserted_count} new · {result.updated_count} updated · {result.rejected_count} skipped
              </p>
              <LightButton onClick={() => router.push('/closet')} style={{ height: 48, padding: '0 26px' }}>
                View closet
              </LightButton>
            </>
          ) : (
            <>
              <h1 className="m-0 text-[22px] font-bold text-white">Review complete</h1>
              <p className="mt-2 mb-7 text-[14px]" style={{ color: 'rgba(255,255,255,0.6)' }}>
                {accepted.length} to add · {rejected.length} skipped
              </p>
              {confirmError && (
                <p className="mb-4 text-[13px]" style={{ color: 'var(--danger)' }}>
                  {confirmError}
                </p>
              )}
              <LightButton
                onClick={handleConfirm}
                disabled={confirming || accepted.length === 0}
                style={{ height: 48, padding: '0 26px' }}
              >
                {confirming
                  ? 'Adding…'
                  : `Add ${accepted.length} to closet`}
              </LightButton>
              {accepted.length === 0 && (
                <button
                  type="button"
                  onClick={() => router.push('/closet')}
                  className="mt-4 text-[13px] underline"
                  style={{ color: 'rgba(255,255,255,0.5)' }}
                >
                  Nothing to add — go to closet
                </button>
              )}
            </>
          )}
        </div>
      </AppShell>
    );
  }

  // ── Deck ───────────────────────────────────────────────────────────────────
  const conf = current.confidence_overall ?? 0;
  const confLow = conf < 0.7;
  const cardEdits = edits[current.candidate_id] ?? {};
  const name = (cardEdits.name as string) ?? current.name ?? 'Unknown item';
  const category = (cardEdits.category as string) ?? current.category ?? '';
  const color = (cardEdits.color as string) ?? current.color ?? '';
  const size = (cardEdits.size as string) ?? current.size ?? '';
  const price =
    cardEdits.unit_price != null ? Number(cardEdits.unit_price) : current.unit_price;

  // Data-driven chips: only those with a value render, so photo items (no price/brand)
  // degrade gracefully — never a blank "Price $" or empty chip.
  const currencySymbol =
    current.currency === 'GBP' ? '£' : current.currency === 'EUR' ? '€' : '$';
  const chips: { label: string; value: string }[] = [];
  if (category) chips.push({ label: 'Category', value: category.charAt(0).toUpperCase() + category.slice(1) });
  if (color) chips.push({ label: 'Color', value: color });
  if (size) chips.push({ label: 'Size', value: size });
  if (price != null && Number.isFinite(Number(price))) {
    chips.push({ label: 'Price', value: `${currencySymbol}${Number(price).toFixed(2)}` });
  }

  // Wave 2 card image selection. A photo card shows the VERIFIED generated product card
  // once ready; while it's being made — or the run is still generating and this card
  // hasn't flipped to a status yet — it shows a "creating…" state, NEVER the raw crop
  // (a full-scene shot with face/background). pending_retry/failed fall back to the crop
  // with a subtle "Preview" tag (the item still gets an image on confirm). Gmail cards
  // (generation_status null, unscoped) are unaffected — they render image_url as before.
  const genStatus = current.generation_status;
  const isPhotoCard = current.source_type === 'photo';
  const generatedReady = genStatus === 'ready' && !!current.generated_image_url;
  const showGenerating =
    isPhotoCard && (genStatus === 'generating' || (genStatus == null && runGenerating));
  const showPreviewTag = isPhotoCard && (genStatus === 'pending_retry' || genStatus === 'failed');
  const cardSrc = generatedReady ? current.generated_image_url : current.image_url;

  // True while this run is still generating product cards — gates the non-blocking
  // "Tailor in the background" escape below.
  const deckGenerating =
    runGenerating || candidates.some((c) => c.generation_status === 'generating');

  // Escape hatch: leave the blocking deck while generation continues server-side. Stash
  // this run so the GenerationProgressPill can resurface on /add-photo and pop the deck
  // back up (/review?sync_id=…) the moment it's ready. Only meaningful for a scoped run.
  function handleReviewInBackground() {
    const syncId = scopeSyncIdRef.current;
    if (!syncId) return;
    useGenerationStore.getState().setPending({ syncId, staged: candidates.length });
    router.push('/add-photo');
  }

  // Alternating stack tilt: even cards lean left (−2°), odd cards lean right (+2°), so a
  // card and the one peeking behind it lean opposite ways.
  const baseRot = index % 2 === 0 ? -2 : 2;

  // Drag-to-swipe: release past this many px commits (accept right / skip left).
  const SWIPE_COMMIT = 90;
  const acceptHint = Math.max(0, Math.min(1, drag.x / SWIPE_COMMIT));
  const rejectHint = Math.max(0, Math.min(1, -drag.x / SWIPE_COMMIT));

  function onSwipeDown(e: React.PointerEvent) {
    if (editing) return; // don't hijack drags on the inline-edit inputs
    dragStartRef.current = e.clientX;
    dragXRef.current = 0;
    setDrag({ x: 0, dragging: true });
    e.currentTarget.setPointerCapture?.(e.pointerId);
  }
  function onSwipeMove(e: React.PointerEvent) {
    if (dragStartRef.current == null) return;
    const dx = e.clientX - dragStartRef.current;
    dragXRef.current = dx;
    setDrag({ x: dx, dragging: true });
  }
  function onSwipeEnd() {
    if (dragStartRef.current == null) return;
    const dx = dragXRef.current;
    dragStartRef.current = null;
    dragXRef.current = 0;
    if (Math.abs(dx) > SWIPE_COMMIT) {
      // Past the line → commit NOW (synchronous, like the buttons). No timer/transition
      // dependency, so a background image-poll re-render can't strand the card off-screen.
      // dragging:true resets the offset with transitions OFF, so the next card appears
      // centered instantly instead of sliding in from the fling position.
      if (dx > 0) handleAccept();
      else handleReject();
      setDrag({ x: 0, dragging: true });
    } else {
      setDrag({ x: 0, dragging: false }); // didn't cross the line → snap back (animated)
    }
  }

  return (
    <AppShell scroll={false}>
      <div className="flex h-full flex-col px-5 pt-12 pb-8">
        {/* Header */}
        <div className="flex items-baseline justify-between">
          <h1 className="m-0 text-[20px] font-bold text-white">Review imports</h1>
          <span className="text-[13px]" style={{ color: 'rgba(255,255,255,0.6)' }}>
            {index + 1} of {total}
          </span>
        </div>
        <p className="mt-1 text-[13.5px]" style={{ color: 'rgba(255,255,255,0.6)' }}>
          Swipe right to add, left to skip.
        </p>

        {/* Live scanning banner — present while a sync is still staging cards. */}
        {scanning && (
          <div
            className="mt-3 flex items-center gap-2 rounded-xl px-3 py-2"
            style={{ background: 'var(--tr-10)', border: '1px solid var(--tr-20)' }}
          >
            <div
              className="h-3.5 w-3.5 rounded-full"
              style={{ border: '2px solid var(--tr-20)', borderTopColor: 'var(--mint)', animation: 'tailor-spin 0.8s linear infinite' }}
            />
            <span className="text-[12.5px]" style={{ color: 'rgba(255,255,255,0.7)' }}>
              Scanning your inbox… more items appear as we find them
              {scanCount > 0 ? ` · ${scanCount} found` : ''}
            </span>
          </div>
        )}

        {/* Non-blocking escape while product cards are still being tailored: leave the
            deck and get pulled back by the progress pill the moment they're ready. */}
        {deckGenerating && (
          <button
            type="button"
            onClick={handleReviewInBackground}
            className="mt-3 inline-flex items-center gap-2 self-start rounded-full px-3.5 py-2 text-[12.5px] font-semibold active:scale-95"
            style={{
              background: 'var(--tr-10)',
              border: '1px solid var(--tr-20)',
              color: 'rgba(255,255,255,0.85)',
              transition: 'transform 120ms var(--ease-out)',
            }}
          >
            <Sparkles size={14} style={{ color: 'var(--mint)' }} />
            Tailor in the background
          </button>
        )}

        {/* Card area */}
        <div className="relative mt-6 flex-1">
          {/* Peeking cards behind */}
          <div
            className="absolute left-1/2 top-2 -translate-x-1/2 rounded-3xl"
            style={{
              width: '94%',
              height: 'calc(100% - 16px)',
              transform: `translateX(-50%) scale(0.94) rotate(${baseRot}deg)`,
              background: '#2a2a2a',
              border: '1px solid var(--tr-10)',
              opacity: 0.5,
            }}
            aria-hidden
          />
          <div
            className="absolute left-1/2 top-1 -translate-x-1/2 rounded-3xl"
            style={{
              width: '97%',
              height: 'calc(100% - 8px)',
              transform: `translateX(-50%) scale(0.97) rotate(${-baseRot}deg)`,
              background: '#2f2f2f',
              border: '1px solid var(--tr-10)',
              opacity: 0.75,
            }}
            aria-hidden
          />

          {/* Top card — flex column so the body (name/category/brand/chips) is ALWAYS
              rendered: the image flexes into whatever space is left and shrinks on
              short viewports instead of pushing the text out of the clipped card. */}
          <div
            className="absolute inset-0 flex flex-col overflow-hidden rounded-3xl"
            onPointerDown={onSwipeDown}
            onPointerMove={onSwipeMove}
            onPointerUp={onSwipeEnd}
            onPointerCancel={onSwipeEnd}
            style={{
              background: '#222',
              border: '1px solid var(--tr-20)',
              boxShadow: '0 20px 40px rgba(0,0,0,0.5)',
              transform: `translateX(${drag.x}px) rotate(${baseRot + drag.x * 0.04}deg)`,
              transition: drag.dragging ? 'none' : 'transform 200ms var(--ease-out)',
              cursor: 'grab',
              touchAction: 'none',
              userSelect: 'none',
            }}
          >
            {/* Image — verified-only (only ever set after vision-verify). While the
                background fill is still resolving, show a soft shimmer instead of a
                broken/wrong image; an exhausted card falls back to a neutral panel.
                flex-1 + min-h-0 lets it absorb spare height yet yield to the body. */}
            {/* Width-derived aspect box: the frame width is definite (max-w-[430px]), so
                aspect-[3/4] yields a definite HEIGHT with zero dependency on the
                main→min-h-full→h-full ancestor chain. The image region can never collapse
                to 0px regardless of ancestors (the bug that hid loaded cutouts). */}
            <div className="relative w-full aspect-[1/1]">
              {showGenerating ? (
                // Photo card mid-generation: a clearly-visible "tailoring" loading state —
                // a LIFTED neutral panel (distinct from the #222 card) with a moving sheen,
                // a bright spinner and copy on top. Never the raw full-scene crop, never a
                // blank panel. (Earlier this was #2c2c2c-on-#222 with a 0.2-alpha ring + a
                // dark gradient painted over it → it read as an empty black rectangle.)
                <div
                  className="absolute inset-0 flex flex-col items-center justify-center gap-2.5 overflow-hidden"
                  style={{ background: '#33343a' }}
                  role="status"
                  aria-label="Tailoring your item"
                >
                  {/* Moving sheen: a wide highlight bar sweeping across (clipped by the
                      panel's overflow-hidden). Reads unmistakably as "working". */}
                  <div
                    className="pointer-events-none absolute inset-y-0 left-0"
                    style={{
                      width: '60%',
                      background:
                        'linear-gradient(100deg, transparent 0%, rgba(255,255,255,0.13) 50%, transparent 100%)',
                      animation: 'tailor-shimmer 1.6s ease-in-out infinite',
                    }}
                    aria-hidden
                  />
                  <div
                    className="relative h-9 w-9 rounded-full"
                    style={{
                      border: '3px solid rgba(255,255,255,0.18)',
                      borderTopColor: 'var(--mint)',
                      animation: 'tailor-spin 0.8s linear infinite',
                    }}
                  />
                  <span className="relative text-[13.5px] font-semibold" style={{ color: 'rgba(255,255,255,0.92)' }}>
                    Tailoring your item…
                  </span>
                  <span className="relative text-[11.5px]" style={{ color: 'rgba(255,255,255,0.5)' }}>
                    Pressing a clean product shot
                  </span>
                </div>
              ) : current.image_status === 'pending' && !current.image_url ? (
                // Gmail card still resolving in the background fill — soft shimmer, not a
                // wrong image.
                <div className="absolute inset-0 animate-pulse" style={{ background: '#3a3a3a' }} aria-label="Resolving image" />
              ) : (
                // Shared render path: opaque neutral backing + absolute-fill <img>. contain
                // shows the WHOLE card (cover would crop it). cardSrc is the generated
                // product card when ready, else the crop fallback.
                <ItemImage key={current.candidate_id} src={cardSrc} alt={name} fit="contain" emptyLabel="No image" />
              )}
              {/* Gradient fade: blends a real image's bottom into the dark info panel
                  (#222). Gated OFF the generating state — over the loading panel it only
                  darkened the copy (part of the "black card" bug). */}
              {!showGenerating && (
                <div
                  className="pointer-events-none absolute inset-0"
                  style={{ background: 'linear-gradient(to top, rgba(0,0,0,0.6), transparent 55%)' }}
                  aria-hidden
                />
              )}
              <span
                className="absolute left-3 top-3 inline-flex items-center gap-1.5 text-[11px] font-semibold"
                style={{
                  color: 'var(--brand-teal)',
                  background: 'var(--mint)',
                  borderRadius: 999,
                  padding: '4px 10px',
                }}
              >
                {/* Source-aware: the deck serves both Gmail and photo candidates. */}
                {current.source_type === 'photo' ? (
                  <>
                    <Camera size={13} /> From your photo
                  </>
                ) : (
                  <>✦ Detected in Gmail</>
                )}
              </span>

              {/* Generation held (pending_retry / failed): the crop stands in as a preview
                  — a subtle tag signals it isn't the final product card. Never blocks confirm. */}
              {showPreviewTag && (
                <span
                  className="absolute right-3 top-3 inline-flex items-center text-[10.5px] font-semibold"
                  style={{
                    color: 'rgba(255,255,255,0.85)',
                    background: 'rgba(0,0,0,0.5)',
                    border: '1px solid var(--tr-20)',
                    borderRadius: 999,
                    padding: '3px 9px',
                  }}
                >
                  Preview
                </span>
              )}

              {/* Swipe affordance stamps — fade in with drag distance/direction. */}
              <span
                aria-hidden
                className="absolute font-bold"
                style={{
                  top: '38%', left: 18, transform: 'translateY(-50%) rotate(-14deg)',
                  opacity: rejectHint, transition: drag.dragging ? 'none' : 'opacity 150ms',
                  border: '3px solid var(--danger)', color: 'var(--danger)',
                  borderRadius: 8, padding: '2px 12px', fontSize: 22, letterSpacing: 1,
                  pointerEvents: 'none',
                }}
              >
                SKIP
              </span>
              <span
                aria-hidden
                className="absolute font-bold"
                style={{
                  top: '38%', right: 18, transform: 'translateY(-50%) rotate(14deg)',
                  opacity: acceptHint, transition: drag.dragging ? 'none' : 'opacity 150ms',
                  border: '3px solid var(--mint)', color: 'var(--mint)',
                  borderRadius: 8, padding: '2px 12px', fontSize: 22, letterSpacing: 1,
                  pointerEvents: 'none',
                }}
              >
                ADD
              </span>
            </div>

            {/* Body — shrink-0: the textual facts always render in full; only the
                image above gives up space when the card is short. */}
            <div className="shrink-0" style={{ padding: '14px 16px' }}>
              <div className="flex items-start justify-between gap-2">
                <h2 className="m-0 text-[19px] font-bold leading-tight text-white">{name}</h2>
                <span className="flex items-center gap-1.5" style={{ flexShrink: 0 }}>
                  <ConfidenceDot conf={conf} />
                  <span
                    className="text-[12px]"
                    style={{ color: confLow ? 'var(--amber)' : 'var(--mint)' }}
                  >
                    {Math.round(conf * 100)}%
                  </span>
                </span>
              </div>

              {current.brand && (
                <p
                  className="m-0 font-accent uppercase"
                  style={{ color: 'rgba(255,255,255,0.6)', fontSize: 13, letterSpacing: '0.4px', marginTop: 2 }}
                >
                  {current.brand}
                </p>
              )}

              {/* Fact chips — data-driven; renders only populated chips. */}
              {chips.length > 0 && (
                <div className="mt-3 flex flex-wrap gap-2">
                  {chips.map((c) => (
                    <FactChip key={c.label} label={c.label} value={c.value} />
                  ))}
                </div>
              )}

              {/* Inline editor */}
              {editing && (
                <div className="mt-4 space-y-2">
                  {(
                    [
                      ['name', 'Name', name],
                      ['color', 'Color', color],
                      ['size', 'Size', size],
                      ['unit_price', 'Price', price != null ? String(price) : ''],
                    ] as const
                  ).map(([field, label, value]) => (
                    <div key={field} className="flex items-center gap-2">
                      <span className="text-[12px]" style={{ width: 52, color: 'rgba(255,255,255,0.55)' }}>
                        {label}
                      </span>
                      <input
                        type={field === 'unit_price' ? 'number' : 'text'}
                        defaultValue={value}
                        onChange={(e) => setEdit(field, e.target.value)}
                        className="flex-1 rounded-lg px-2 py-1.5 text-[14px] text-white outline-none"
                        style={{ background: 'rgba(255,255,255,0.1)', border: '1px solid var(--tr-20)' }}
                      />
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Action buttons */}
        <div className="mt-6 flex items-center justify-center gap-[18px]">
          <button
            type="button"
            onClick={handleReject}
            aria-label="Skip"
            className="flex items-center justify-center transition-transform active:scale-90"
            style={{
              width: 60,
              height: 60,
              borderRadius: '50%',
              background: 'rgba(0,0,0,0.3)',
              border: '1px solid var(--tr-20)',
              color: '#fff',
            }}
          >
            <X size={26} />
          </button>

          <button
            type="button"
            onClick={() => setEditing((e) => !e)}
            aria-label="Edit"
            className="flex items-center justify-center transition-transform active:scale-90"
            style={{
              width: 50,
              height: 50,
              borderRadius: '50%',
              background: editing ? 'var(--tr-20)' : 'rgba(0,0,0,0.3)',
              border: '1px solid var(--tr-20)',
              color: 'rgba(255,255,255,0.85)',
            }}
          >
            <Pencil size={20} />
          </button>

          <button
            type="button"
            onClick={handleAccept}
            aria-label="Add"
            className="flex items-center justify-center transition-transform active:scale-90"
            style={{
              width: 68,
              height: 68,
              borderRadius: '50%',
              background: 'var(--mint)',
              color: 'var(--brand-teal)',
              boxShadow: '0 8px 24px rgba(75,226,214,0.3)',
            }}
          >
            <Check size={30} strokeWidth={2.5} />
          </button>
        </div>
      </div>
    </AppShell>
  );
}
