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
import { Check, Mail, Pencil, X } from 'lucide-react';

import { useRequireAuth } from '@/lib/auth/useRequireAuth';
import { useClosetStore } from '@/stores/useClosetStore';
import {
  confirmCandidates,
  getIngestCandidates,
  getIngestStatus,
  startIngest,
  type ConfirmResponse,
  type IngestCandidate,
} from '@/lib/api/gmail';
import { AppShell } from '@/components/layout/AppShell';
import { ConfidenceDot } from '@/components/ui/ConfidenceDot';
import { LightButton } from '@/components/ui/LightButton';
import { EmptyState } from '@/components/ui/EmptyState';

type CardEdits = Record<string, Record<string, unknown>>;

const FALLBACK_IMG =
  'data:image/svg+xml;utf8,' +
  encodeURIComponent(
    "<svg xmlns='http://www.w3.org/2000/svg' width='400' height='400'><rect width='100%' height='100%' fill='%23333'/></svg>"
  );

function FactChip({ children }: { children: React.ReactNode }) {
  return (
    <span
      className="inline-flex items-center text-[12.5px] text-white/85"
      style={{
        background: 'var(--tr-10)',
        border: '1px solid var(--tr-20)',
        borderRadius: 10,
        padding: '5px 10px',
      }}
    >
      {children}
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

  const mountedRef = useRef(true);
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

  // While images keep resolving in the background, poll candidates to swap them in.
  // This only READS candidates — it never starts a sync.
  const pollImages = useCallback(async function pollImages() {
    if (!mountedRef.current) return;
    try {
      const cands = await getIngestCandidates();
      if (!mountedRef.current) return;
      mergeCandidates(cands);
      if (cands.some((c) => c.image_status === 'pending')) schedule(pollImages, 2500);
    } catch {
      /* transient — a manual refresh recovers */
    }
  }, [mergeCandidates, schedule]);

  // While the sync runs, stream staged cards + keep the scanning count live. Reads
  // status/candidates only — it does NOT (re)start a sync.
  const pollSync = useCallback(async function pollSync(syncId: string) {
    if (!mountedRef.current) return;
    try {
      const [st, cands] = await Promise.all([getIngestStatus(syncId), getIngestCandidates()]);
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
    setLoading(true);
    getIngestCandidates()
      .then((cands) => {
        if (!mountedRef.current) return;
        setCandidates(cands);
        setLoading(false);
        if (cands.some((c) => c.image_status === 'pending')) pollImages();
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

        {/* Card area */}
        <div className="relative mt-6 flex-1">
          {/* Peeking cards behind */}
          <div
            className="absolute left-1/2 top-2 -translate-x-1/2 rounded-3xl"
            style={{
              width: '94%',
              height: 'calc(100% - 16px)',
              transform: 'translateX(-50%) scale(0.94)',
              background: '#2a2a2a',
              border: '1px solid var(--tr-10)',
              opacity: 0.4,
            }}
            aria-hidden
          />
          <div
            className="absolute left-1/2 top-1 -translate-x-1/2 rounded-3xl"
            style={{
              width: '97%',
              height: 'calc(100% - 8px)',
              transform: 'translateX(-50%) scale(0.97)',
              background: '#262626',
              border: '1px solid var(--tr-10)',
              opacity: 0.6,
            }}
            aria-hidden
          />

          {/* Top card — flex column so the body (name/category/brand/chips) is ALWAYS
              rendered: the image flexes into whatever space is left and shrinks on
              short viewports instead of pushing the text out of the clipped card. */}
          <div
            className="absolute inset-0 flex flex-col overflow-hidden rounded-3xl"
            style={{
              background: '#222',
              border: '1px solid var(--tr-20)',
              boxShadow: 'var(--shadow-lg)',
              transform: 'rotate(-2deg)',
            }}
          >
            {/* Image — verified-only (only ever set after vision-verify). While the
                background fill is still resolving, show a soft shimmer instead of a
                broken/wrong image; an exhausted card falls back to a neutral panel.
                flex-1 + min-h-0 lets it absorb spare height yet yield to the body. */}
            <div className="relative w-full flex-1 min-h-0" style={{ background: '#333' }}>
              {current.image_url ? (
                /* eslint-disable-next-line @next/next/no-img-element */
                <img
                  src={current.image_url}
                  alt={name}
                  className="h-full w-full object-cover"
                  // A resolved URL that fails to load (404 / CORS / hotlink block) must
                  // degrade to the neutral panel — never a broken-image glyph. Clearing
                  // onerror first prevents a loop if the fallback itself ever failed.
                  onError={(e) => {
                    e.currentTarget.onerror = null;
                    e.currentTarget.src = FALLBACK_IMG;
                  }}
                />
              ) : current.image_status === 'pending' ? (
                <div className="h-full w-full animate-pulse" style={{ background: '#3a3a3a' }} aria-label="Resolving image" />
              ) : (
                /* eslint-disable-next-line @next/next/no-img-element */
                <img src={FALLBACK_IMG} alt={name} className="h-full w-full object-cover" />
              )}
              <span
                className="absolute left-3 top-3 inline-flex items-center gap-1 text-[12px] font-medium"
                style={{
                  color: 'var(--brand-teal)',
                  background: 'var(--mint)',
                  borderRadius: 999,
                  padding: '4px 10px',
                }}
              >
                ✦ Detected in Gmail
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
                    className="text-[13px] font-semibold"
                    style={{ color: confLow ? 'var(--amber)' : 'var(--mint)' }}
                  >
                    {Math.round(conf * 100)}%
                  </span>
                </span>
              </div>

              {current.brand && (
                <p
                  className="m-0 mt-1 font-accent uppercase"
                  style={{ color: 'rgba(255,255,255,0.6)', fontSize: 12, letterSpacing: '0.5px' }}
                >
                  {current.brand}
                </p>
              )}

              {/* Fact chips */}
              <div className="mt-3 flex flex-wrap gap-2">
                {category && (
                  <FactChip>{category.charAt(0).toUpperCase() + category.slice(1)}</FactChip>
                )}
                {color && <FactChip>{color}</FactChip>}
                {size && <FactChip>Size {size}</FactChip>}
                {price != null && Number.isFinite(price) && (
                  <FactChip>
                    {current.currency === 'GBP' ? '£' : current.currency === 'EUR' ? '€' : '$'}
                    {price.toFixed(2)}
                  </FactChip>
                )}
              </div>

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
              color: 'var(--danger)',
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
