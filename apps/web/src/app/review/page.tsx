'use client';

/**
 * /review — Gmail receipt + photo swipe-review deck (variation A, decision-first).
 *
 * Loads pending ingest candidates, lets the user accept / reject / edit each one
 * via a card deck, then confirms the batch into the closet. Replaces the old
 * /gmail-sync flow; wired to the real ingest candidates + confirm endpoints.
 */

import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import { motion } from 'framer-motion';
import { Camera, Check, Mail, Pencil, X } from 'lucide-react';

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
  type IngestCandidate,
} from '@/lib/api/gmail';
import { AppShell } from '@/components/layout/AppShell';
import { ItemImage } from '@/components/ui/ItemImage';
import { ConfidenceDot } from '@/components/ui/ConfidenceDot';
import {
  Btn,
  RoundBtn,
  Spark,
  M,
  TopBar,
  StateBlock,
  ErrorState,
  OfflineScreen,
  RateLimitState,
  DeckLoading,
  SuccessPop,
} from '@/components/ds';

type CardEdits = Record<string, Record<string, unknown>>;

// UI-only quota affordance. There is NO server quota enforcement (locked copy: free tier
// tailors "30 photos a month"); this only recognises an error that *reads* like a limit so
// the RateLimitState template can be shown instead of a raw error string.
function looksLikeQuota(msg: string | null): boolean {
  if (!msg) return false;
  return /limit|quota|too many|rate|429|30 photos/i.test(msg);
}

// The URL a card WILL paint into its <img>, or null if the card shows a non-image state
// (still-generating "tailoring" placeholder / resolving shimmer) and so needs no warming.
function cardImageUrl(c: IngestCandidate | undefined): string | null {
  if (!c) return null;
  if (c.generation_status === 'ready' && c.generated_image_url) return c.generated_image_url;
  // Photo cards mid-generation show the placeholder, not the raw crop — nothing to warm.
  if (c.source_type === 'photo' && (c.generation_status === 'generating' || c.generation_status == null)) {
    return null;
  }
  // Gmail cards / exhausted photo cards paint image_url (once resolved).
  return c.image_status === 'pending' ? null : c.image_url ?? null;
}

// URLs already handed to the browser this session — warming the same one twice is wasted
// work (and re-creating an Image can even evict a fresh decode on some browsers).
const warmed = new Set<string>();

// Warm the browser cache AND decode the image each card WILL show, so the visible <img>
// paints instantly — no white flash on the first card or on advance. `img.decode()`
// pulls the bytes AND rasterizes them off-thread; a plain `img.src =` (the prior attempt)
// only primed the HTTP cache, so the visible <img> still had to decode on the main thread
// at paint time and flashed the panel meanwhile. The bg-sampling probe is separate.
function warmCardImages(cands: IngestCandidate[], from: number, to: number) {
  if (typeof window === 'undefined') return;
  for (let i = Math.max(0, from); i <= to; i++) {
    const url = cardImageUrl(cands[i]);
    if (!url || warmed.has(url)) continue;
    warmed.add(url);
    const img = new window.Image();
    img.src = url;
    void img.decode?.().catch(() => {});
  }
}

// Fully decode `url` before resolving, capped so a slow/broken image can never hang the
// deck reveal. Used to hold the loading spinner until the FIRST card's image is ready to
// paint — the deck then appears with its image already on screen instead of white.
function decodeUrl(url: string, capMs = 600): Promise<void> {
  return new Promise((resolve) => {
    if (typeof window === 'undefined') return resolve();
    const img = new window.Image();
    const cap = setTimeout(resolve, capMs);
    const done = () => {
      clearTimeout(cap);
      resolve();
    };
    img.src = url;
    if (img.decode) img.decode().then(done, done);
    else {
      img.onload = done;
      img.onerror = done;
    }
    warmed.add(url);
  });
}

// A bordered "Label Value" pill (Option A). Label muted, value bold. Only rendered by
// the caller when the value exists — never a blank/empty chip.
function FactChip({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <span
      className="inline-flex items-center gap-1.5"
      style={{
        background: 'rgba(255,255,255,0.07)',
        border: '1px solid rgba(255,255,255,0.12)',
        borderRadius: 999,
        padding: '6px 12px',
      }}
    >
      <span style={{ color: M.faint, fontSize: 11 }}>{label}</span>
      <span className="font-semibold text-white" style={{ fontSize: 12.5 }}>{value}</span>
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

  // Auto-add + auto-advance: reaching the end of the deck commits the accepted batch and
  // navigates to the closet after a short countdown — no "Add to closet" press. The commit
  // fires once (memoized promise); navigation awaits it so the closet shows the new items.
  const autoCommitRef = useRef<Promise<void> | null>(null);
  const leftRef = useRef(false);
  const [autoError, setAutoError] = useState<string | null>(null);

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
      .then(async (cands) => {
        if (!mountedRef.current) return;
        // Warm the first cards' images now, then HOLD the loading spinner until the very
        // first card's image has fully decoded — so the deck's first paint already carries
        // its image instead of flashing the panel while the <img> loads. Capped inside
        // decodeUrl so a slow/absent image can't stall the deck. This is why the earlier
        // "warm the cache" attempt didn't help: it ran in the same commit as the render,
        // giving the visible <img> zero head start.
        warmCardImages(cands, 0, 2);
        const firstUrl = cardImageUrl(cands[0]);
        if (firstUrl) await decodeUrl(firstUrl);
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

  // Warm the CURRENT + next couple of card images so they paint instantly — the current
  // covers the first-card-on-return case; the look-ahead covers swipes. Re-runs when a
  // poll flips a card to 'ready', warming its freshly-generated image before it shows.
  useEffect(() => {
    warmCardImages(candidates, index, index + 2);
  }, [index, candidates]);

  // Reached the end of a decided deck (not still scanning) → auto-commit the batch and
  // auto-advance to the closet after a 1.5s countdown (the top bar shows it coming). No
  // button press. Commit fires immediately for a head start; the timer navigates.
  const deckComplete =
    !loading && !loadError && candidates.length > 0 && index >= candidates.length && !scanning;
  useEffect(() => {
    if (!deckComplete) return;
    setAutoError(null);
    void commitBatch();
    const t = setTimeout(() => void finishAndGo(), 1500);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [deckComplete]);

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

  // Commit the accepted batch exactly once. Memoized so the on-mount head-start call and a
  // later tap/timer share ONE POST. On failure the memo resets so a tap can retry.
  function commitBatch(): Promise<void> {
    if (autoCommitRef.current) return autoCommitRef.current;
    autoCommitRef.current =
      accepted.length === 0
        ? Promise.resolve()
        : confirmCandidates({ accepted, rejected, edits })
            .then(() => {
              useClosetStore.getState().invalidate();
              // This run's batch is decided — drop any pending "review in background" pill.
              useGenerationStore.getState().clear();
            })
            .catch((err) => {
              autoCommitRef.current = null; // allow a retry tap
              setAutoError(err instanceof Error ? err.message : 'Failed to add items.');
              throw err;
            });
    return autoCommitRef.current;
  }

  // Await the commit (usually already resolved from the head start), then go to the closet.
  // Fires from the 1.5s countdown OR an early tap. Stays put on commit failure so the
  // error + retry are visible instead of stranding the user.
  async function finishAndGo() {
    if (leftRef.current) return;
    try {
      await commitBatch();
    } catch {
      return;
    }
    leftRef.current = true;
    router.push('/closet');
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
    // Neutral load copy — this is just fetching already-staged candidates, NOT a live scan.
    // Opening a COMPLETE run from the Home banner must not read as "scanning" (G5); the real
    // live-scan UI is the scanning=true state below, only reached via an explicit Scan tap.
    return (
      <AppShell scroll={false}>
        <div className="flex h-full flex-col px-5 pt-[62px]">
          <TopBar title="Review finds" onBack={() => router.back()} />
          <div className="flex flex-1 items-center justify-center">
            <DeckLoading label="Loading your review…" />
          </div>
        </div>
      </AppShell>
    );
  }

  if (loadError) {
    // Offline vs. generic failure vs. a limit-shaped error — pick the honest §0 template.
    const offline = typeof navigator !== 'undefined' && navigator.onLine === false;
    return (
      <AppShell scroll={false}>
        <div className="flex h-full flex-col px-5 pt-[62px]">
          <TopBar title="Review finds" onBack={() => router.back()} />
          <div className="flex flex-1 items-center justify-center">
            {offline ? (
              <OfflineScreen
                context="We can't reach your receipts right now. Your closet is saved on this phone."
                onRetry={() => router.refresh()}
                onBrowseCloset={() => router.push('/closet')}
              />
            ) : looksLikeQuota(loadError) ? (
              <RateLimitState
                title="Detection limit reached"
                sub="Free plans tailor 30 photos a month. Yours refreshes soon —"
                reset="in a few days"
                onBrowseCloset={() => router.push('/closet')}
              />
            ) : (
              <ErrorState
                title="Couldn't load imports"
                sub={loadError}
                onRetry={() => router.refresh()}
                retryLabel="Try again"
              />
            )}
          </div>
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
          <div className="flex h-full flex-col px-5 pt-[62px]">
            <TopBar title="Review finds" sub="Scanning your inbox…" onBack={() => router.back()} />
            <div className="flex flex-1 flex-col items-center justify-center">
              <DeckLoading
                label={
                  scanCount > 0
                    ? `${scanCount} found so far — first cards appear in a moment`
                    : 'Finding clothing purchases in your receipts'
                }
              />
            </div>
          </div>
        </AppShell>
      );
    }
    // A scan error that reads like a limit → the honest quota template (locked copy).
    if (looksLikeQuota(scanError)) {
      return (
        <AppShell scroll={false}>
          <div className="flex h-full flex-col px-5 pt-[62px]">
            <TopBar title="Review finds" onBack={() => router.back()} />
            <div className="flex flex-1 items-center justify-center">
              <RateLimitState
                title="Detection limit reached"
                sub="Free plans tailor 30 photos a month. Yours refreshes soon —"
                reset="in a few days"
                onBrowseCloset={() => router.push('/closet')}
              />
            </div>
          </div>
        </AppShell>
      );
    }
    // Gmail not connected yet — the designed "Connect Gmail to begin" prompt.
    if (gmailConnected === false) {
      return (
        <AppShell scroll={false}>
          <div className="flex h-full flex-col px-5 pt-[62px]">
            <TopBar title="Review finds" onBack={() => router.back()} />
            <div className="flex flex-1 items-center justify-center">
              <StateBlock
                icon={<Mail size={28} />}
                title="Connect Gmail to begin"
                sub="Tailor builds your closet from email receipts. Connect once and items appear automatically."
                cta={
                  <Btn
                    variant="primary"
                    size="md"
                    icon={<Mail size={16} />}
                    pending={connectBusy}
                    onClick={() => {
                      if (connectBusy) return;
                      setConnectBusy(true);
                      startGmailConnect().catch(() => setConnectBusy(false));
                    }}
                  >
                    {connectBusy ? 'Opening Google…' : 'Connect Gmail'}
                  </Btn>
                }
                cta2={
                  <Btn variant="ghost" size="md" onClick={() => router.push('/closet')}>
                    Back to closet
                  </Btn>
                }
                foot="Read-only · receipts only · revoke anytime"
              />
            </div>
          </div>
        </AppShell>
      );
    }
    return (
      <AppShell scroll={false}>
        <div className="flex h-full flex-col px-5 pt-[62px]">
          <TopBar title="Review finds" onBack={() => router.back()} />
          <div className="flex flex-1 items-center justify-center">
            <StateBlock
              icon={<Mail size={28} />}
              title="Nothing to review"
              sub="Scan your Gmail receipts to find clothing purchases to review."
              cta={
                <Btn variant="primary" size="md" icon={<Mail size={16} />} pending={starting} onClick={handleScan}>
                  {starting ? 'Starting…' : 'Scan my inbox'}
                </Btn>
              }
              cta2={
                <Btn variant="ghost" size="md" onClick={() => router.push('/profile')}>
                  Manage Gmail connection
                </Btn>
              }
              foot="Read-only · receipts only · revoke anytime"
            />
          </div>
          {scanError && !looksLikeQuota(scanError) && (
            <p
              className="mx-auto mb-6 max-w-[280px] text-center text-[13px]"
              style={{ color: '#ff9096' }}
            >
              {scanError}
            </p>
          )}
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
          <div className="flex h-full flex-col px-5 pt-[62px]">
            <TopBar title="Review finds" sub="Scanning for more…" onBack={() => router.back()} />
            <div className="flex flex-1 flex-col items-center justify-center">
              <DeckLoading label="You're all caught up — new items appear as we find them" />
            </div>
          </div>
        </AppShell>
      );
    }
    // Review complete → auto-add + auto-advance. No button: the batch commits on entry and
    // the top bar depletes over 1.5s, then we navigate. Tapping anywhere commits + goes now.
    return (
      <AppShell scroll={false}>
        <div className="relative h-full">
          {/* Top countdown bar — full-width, depletes to the left over 1.5s so the
              auto-advance is visible. Matches the 1.5s timer in the deckComplete effect. */}
          <motion.div
            className="absolute left-0 top-0 h-[3px] w-full"
            style={{ background: 'var(--mint)', transformOrigin: 'left' }}
            initial={{ scaleX: 1 }}
            animate={{ scaleX: 0 }}
            transition={{ duration: 1.5, ease: 'linear' }}
            aria-hidden
          />
          <button
            type="button"
            onClick={() => void finishAndGo()}
            className="flex h-full w-full flex-col items-center justify-center px-8 text-center"
            aria-label="Add to closet and go now"
          >
            <SuccessPop size={80} />
            <h1 className="mt-6 mb-0 text-[22px] font-bold text-white" style={{ letterSpacing: '-0.4px' }}>
              {accepted.length > 0 ? `Adding ${accepted.length} to your closet` : 'All caught up'}
            </h1>
            <p className="mt-2 text-[14px]" style={{ color: M.faint }}>
              {accepted.length} to add · {rejected.length} skipped
            </p>
            {autoError ? (
              <span className="mt-6 text-[13px]" style={{ color: '#ff9096' }}>
                {autoError} — tap to retry
              </span>
            ) : (
              <span className="mt-6 text-[13px]" style={{ color: M.faint }}>
                Taking you to your closet… <span style={{ color: 'var(--mint)' }}>tap to go now</span>
              </span>
            )}
          </button>
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
  // Photo-seam Phase 3 needs-size affordance: the card is verified + person-free but
  // has no size (no onboarding default). Surface it explicitly — the inline editor
  // (pencil) has a Size field; supplying one completes the item at confirm.
  else if (current.needs_size) chips.push({ label: 'Size', value: 'Add size ✎' });
  if (price != null && Number.isFinite(Number(price))) {
    chips.push({ label: 'Price', value: `${currencySymbol}${Number(price).toFixed(2)}` });
  }

  // Card image selection (Photo-seam Phase 5 — display purity). A photo/manual card
  // shows ONLY the VERIFIED generated product card; the server never sends a raw
  // crop for those sources (image_url is null in the payload), so mid-generation
  // cards show the "tailoring" panel and NOTHING else. Gmail cards render their
  // verified resolved image_url as before. The old Preview-the-crop fallback is
  // gone with the payload that fed it.
  const genStatus = current.generation_status;
  const isPhotoCard = current.source_type === 'photo';
  const generatedReady = genStatus === 'ready' && !!current.generated_image_url;
  const showGenerating =
    isPhotoCard &&
    (genStatus === 'generating' ||
      (genStatus == null && runGenerating) ||
      (!generatedReady && !current.image_url));
  const cardSrc = generatedReady ? current.generated_image_url : current.image_url;

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
      <div className="flex h-full flex-col px-5 pt-[62px] pb-8">
        {/* Header */}
        <TopBar
          title="Review finds"
          sub="Keep it, fix it, or toss it"
          onBack={() => router.back()}
          right={
            <span
              style={{ color: M.faint, fontSize: 12.5, fontVariantNumeric: 'tabular-nums' }}
            >
              {index + 1} of {total}
            </span>
          }
        />

        {/* Live scanning banner — present while a sync is still staging cards. */}
        {scanning && (
          <div
            className="mt-3 flex items-center gap-2 rounded-2xl px-3.5 py-2.5"
            style={{ background: 'rgba(75,226,214,0.10)', border: '1px solid rgba(75,226,214,0.28)' }}
          >
            <div
              className="h-3.5 w-3.5 rounded-full"
              style={{ border: '2px solid var(--tr-20)', borderTopColor: 'var(--mint)', animation: 'tailor-spin 0.8s linear infinite' }}
            />
            <span className="text-[12.5px]" style={{ color: M.soft }}>
              Scanning your inbox… more items appear as we find them
              {scanCount > 0 ? ` · ${scanCount} found` : ''}
            </span>
          </div>
        )}

        {/* Card area */}
        <div className="relative mt-6 flex-1">
          {/* Peeking cards behind */}
          <div
            className="absolute left-1/2 top-2 -translate-x-1/2"
            style={{
              width: '94%',
              height: 'calc(100% - 16px)',
              borderRadius: 28,
              transform: `translateX(-50%) scale(0.94) rotate(${baseRot}deg)`,
              background: 'rgba(255,255,255,0.05)',
              border: '1px solid rgba(255,255,255,0.08)',
              opacity: 0.6,
            }}
            aria-hidden
          />
          <div
            className="absolute left-1/2 top-1 -translate-x-1/2"
            style={{
              width: '97%',
              height: 'calc(100% - 8px)',
              borderRadius: 28,
              transform: `translateX(-50%) scale(0.97) rotate(${-baseRot}deg)`,
              background: 'rgba(255,255,255,0.07)',
              border: '1px solid rgba(255,255,255,0.1)',
              opacity: 0.8,
            }}
            aria-hidden
          />

          {/* Top card — flex column so the body (name/category/brand/chips) is ALWAYS
              rendered: the image flexes into whatever space is left and shrinks on
              short viewports instead of pushing the text out of the clipped card. */}
          <div
            className="absolute inset-0 flex flex-col overflow-hidden"
            onPointerDown={onSwipeDown}
            onPointerMove={onSwipeMove}
            onPointerUp={onSwipeEnd}
            onPointerCancel={onSwipeEnd}
            style={{
              borderRadius: 28,
              background: 'linear-gradient(180deg, rgba(16,32,31,0.82), rgba(9,20,20,0.88))',
              border: '1px solid rgba(255,255,255,0.14)',
              boxShadow: 'inset 0 1px 0 rgba(255,255,255,0.08), 0 24px 60px -12px rgba(0,0,0,0.65)',
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
                aspect-[1/1] yields a definite HEIGHT with zero dependency on the
                main→min-h-full→h-full ancestor chain. The image region can never collapse
                to 0px regardless of ancestors (the bug that hid loaded cutouts). */}
            <div className="relative w-full aspect-[1/1]">
              {showGenerating ? (
                // Photo card mid-generation: a clearly-visible "tailoring" loading state —
                // a LIFTED neutral panel (distinct from the card) with a moving sheen, a
                // bright spinner and copy on top. Never the raw full-scene crop, never a
                // blank panel.
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
                  <span className="relative text-[11.5px]" style={{ color: M.faint }}>
                    Pressing a clean product shot
                  </span>
                </div>
              ) : current.image_status === 'pending' && !current.image_url ? (
                // Gmail card still resolving in the background fill — soft shimmer, not a
                // wrong image.
                <div className="absolute inset-0 animate-pulse" style={{ background: '#3a3a3a' }} aria-label="Resolving image" />
              ) : (
                // Shared render path: absolute-fill <img>, contain shows the WHOLE card
                // (cover would crop it). cardSrc is the generated product card when ready,
                // else the crop fallback. For the generated card we SAMPLE its own bg so
                // the contain letterbox matches the image → seamless full-bleed, no bars.
                <ItemImage
                  key={current.candidate_id}
                  src={cardSrc}
                  alt={name}
                  fit="contain"
                  emptyLabel="No image"
                  sampleBackground={generatedReady}
                />
              )}
              {/* Gradient fade: blends a real image's bottom into the dark info panel.
                  Gated OFF the generating state (it darkened the loading panel) AND the
                  generated card (its sampled pale bg must stay seamless). Kept for Gmail
                  images / crop previews. */}
              {!showGenerating && !generatedReady && (
                <div
                  className="pointer-events-none absolute inset-0"
                  style={{ background: 'linear-gradient(to top, rgba(0,0,0,0.6), transparent 55%)' }}
                  aria-hidden
                />
              )}

              {/* Source badge — chat/photo/Gmail. Chat + photo share the mint "From …"
                  treatment (I8 chat source badge); Gmail keeps the Spark mark. */}
              <span
                className="absolute left-3 top-3 inline-flex items-center gap-1.5 text-[11px] font-semibold"
                style={{
                  color: 'var(--mint)',
                  background: 'rgba(0,0,0,0.5)',
                  backdropFilter: 'blur(10px)',
                  WebkitBackdropFilter: 'blur(10px)',
                  border: '1px solid rgba(75,226,214,0.4)',
                  borderRadius: 999,
                  padding: '5px 11px',
                }}
              >
                {current.source_type === 'photo' ? (
                  <>
                    <Camera size={12} /> From your photo
                  </>
                ) : (
                  <>
                    <Spark size={12} /> Detected in Gmail
                  </>
                )}
              </span>

              {/* Confidence % — top-right glass chip. */}
              <span
                className="absolute right-3 top-3 text-[11px]"
                style={{
                  color: confLow ? '#f0b566' : M.soft,
                  background: 'rgba(0,0,0,0.5)',
                  backdropFilter: 'blur(10px)',
                  WebkitBackdropFilter: 'blur(10px)',
                  border: `1px solid ${confLow ? 'rgba(240,162,59,0.4)' : 'rgba(255,255,255,0.18)'}`,
                  borderRadius: 999,
                  padding: '5px 11px',
                  fontVariantNumeric: 'tabular-nums',
                }}
              >
                {Math.round(conf * 100)}% sure
              </span>

              {/* Swipe affordance stamps — fade in with drag distance/direction. */}
              <span
                aria-hidden
                className="absolute font-bold"
                style={{
                  top: '38%', left: 18, transform: 'translateY(-50%) rotate(-14deg)',
                  opacity: rejectHint, transition: drag.dragging ? 'none' : 'opacity 150ms',
                  border: '3px solid #ff8087', color: '#ff8087',
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
            <div className="shrink-0" style={{ padding: '14px 18px 16px' }}>
              <div className="flex items-start justify-between gap-2">
                <h2 className="m-0 text-[18px] font-bold leading-tight text-white" style={{ letterSpacing: '-0.3px' }}>
                  {name}
                </h2>
                <span className="flex items-center gap-1.5" style={{ flexShrink: 0 }}>
                  <ConfidenceDot conf={conf} />
                  <span
                    className="text-[12px]"
                    style={{ color: confLow ? '#f0b566' : 'var(--mint)' }}
                  >
                    {Math.round(conf * 100)}%
                  </span>
                </span>
              </div>

              {current.brand && (
                <p
                  className="m-0 font-accent uppercase"
                  style={{ color: M.faint, fontSize: 12.5, letterSpacing: '0.6px', marginTop: 2 }}
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
                      <span className="text-[12px]" style={{ width: 52, color: M.faint }}>
                        {label}
                      </span>
                      <input
                        type={field === 'unit_price' ? 'number' : 'text'}
                        defaultValue={value}
                        onChange={(e) => setEdit(field, e.target.value)}
                        className="flex-1 rounded-xl px-3 py-2 text-[14px] text-white outline-none"
                        style={{ background: 'rgba(255,255,255,0.075)', border: '1px solid rgba(255,255,255,0.13)' }}
                      />
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Action buttons — skip · edit · add. */}
        <div className="mt-6 flex items-center justify-center gap-5">
          <RoundBtn size={56} onClick={handleReject} aria-label="Skip" icon={<X size={23} />} />
          <RoundBtn
            size={44}
            on={editing}
            onClick={() => setEditing((e) => !e)}
            aria-label="Edit"
            icon={<Pencil size={18} />}
          />
          <button
            type="button"
            onClick={handleAccept}
            aria-label="Add"
            className="flex items-center justify-center transition-transform active:scale-90"
            style={{
              width: 56,
              height: 56,
              borderRadius: '50%',
              background: 'linear-gradient(165deg, #52e8dc, #2cc9bc)',
              border: '1px solid rgba(255,255,255,0.3)',
              color: '#06302d',
              boxShadow: '0 12px 30px -8px rgba(75,226,214,0.5)',
            }}
          >
            <Check size={24} strokeWidth={2.5} />
          </button>
        </div>

        {/* 24h auto-hang reassurance. */}
        <p className="mt-4 text-center text-[11.5px]" style={{ color: M.ghost }}>
          Unreviewed high-confidence finds hang themselves in 24h — you can always edit later.
        </p>
      </div>
    </AppShell>
  );
}
