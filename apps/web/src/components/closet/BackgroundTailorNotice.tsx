'use client';

/**
 * BackgroundTailorNotice — the "your review is ready" surface for users who chose to
 * tailor in the background (Wave 2, polished).
 *
 * Mounted once globally (AppShell). When a photo run is pending in the generation store
 * AND the user is browsing elsewhere, it shows a non-blocking control:
 *   - appears expanded (§0 ProcessingPill — "Tailoring N…" / "Review N →"),
 *   - a few seconds later minimizes into the small floating disc (tap → re-expands),
 *   - and the moment generation FINISHES it pops back open and pulses/glows to grab
 *     attention so the user notices their review is ready.
 *
 * Reuses useGenerationRunStatus (the shared poll) + the generation store; sync_id is
 * preserved throughout. Hidden on /review (already there) and /add-photo (the preparing
 * screen owns the pill), so only one poller is ever live.
 */
import { useEffect, useRef } from 'react';
import { usePathname, useRouter } from 'next/navigation';
import { AnimatePresence, motion, useMotionValue } from 'framer-motion';
import { Minus, X } from 'lucide-react';

import { ProcessingPill, M } from '@/components/ds';
import { useGenerationStore, type PendingGeneration } from '@/stores/useGenerationStore';
import { useGenerationRunStatus } from './useGenerationRunStatus';

// Session-persisted drag offset (relative to the bottom-right anchor). Kept for the tab
// session so repositioning the control survives navigations and reloads, but never leaks
// into a later session. Read once on mount, written on drag end.
const POS_KEY = 'tailor:bgNoticePos';
function readStoredPos(): { x: number; y: number } {
  if (typeof window === 'undefined') return { x: 0, y: 0 };
  try {
    const raw = window.sessionStorage.getItem(POS_KEY);
    if (raw) {
      const p = JSON.parse(raw);
      if (typeof p?.x === 'number' && typeof p?.y === 'number') return p;
    }
  } catch {
    /* ignore */
  }
  return { x: 0, y: 0 };
}

export function BackgroundTailorNotice() {
  const pathname = usePathname();
  const pending = useGenerationStore((s) => s.pending);
  const onOwnedScreen =
    pathname?.startsWith('/review') || pathname?.startsWith('/add-photo');

  return (
    <AnimatePresence>
      {pending && !onOwnedScreen && (
        <NoticeInner key={pending.syncId ?? 'provisional'} pending={pending} />
      )}
    </AnimatePresence>
  );
}

function NoticeInner({ pending }: { pending: PendingGeneration }) {
  const router = useRouter();
  const clear = useGenerationStore((s) => s.clear);
  const { ready, total, done } = useGenerationRunStatus(pending.syncId, pending.staged);
  // Minimized state lives in the store (module singleton) so it STAYS minimized across
  // navigation — this notice re-mounts per route (AppShell is per-page), and a local
  // useState would reset to expanded on every screen switch (the bug).
  const minimized = useGenerationStore((s) => s.minimized);
  const setMinimized = useGenerationStore((s) => s.setMinimized);
  const expanded = !minimized;
  const setExpanded = (v: boolean) => setMinimized(!v);
  // The ready reveal must fire EXACTLY ONCE per run (store-backed so it isn't re-applied on
  // every remount — otherwise a finished review would re-pop-open on each navigation).
  const revealed = useGenerationStore((s) => s.revealed);
  const setRevealed = useGenerationStore((s) => s.setRevealed);

  // Drag: a session-persisted offset from the bottom-right anchor so the user can move the
  // control off any content it covers, and it stays put across navigations/reloads.
  const constraintsRef = useRef<HTMLDivElement>(null);
  const startPos = useRef(readStoredPos());
  const x = useMotionValue(startPos.current.x);
  const y = useMotionValue(startPos.current.y);
  const persistPos = () => {
    try {
      window.sessionStorage.setItem(POS_KEY, JSON.stringify({ x: x.get(), y: y.get() }));
    } catch {
      /* ignore */
    }
  };

  // Auto-minimize to the side dock a few seconds after appearing — but only while still
  // running (a finished run stays open so its attention reveal is seen).
  useEffect(() => {
    if (done) return;
    const t = setTimeout(() => setExpanded(false), 4000);
    return () => clearTimeout(t);
  }, [done]);

  // Finished → pop back open ONCE and latch `revealed` so the attention keyframe plays a
  // single time and then the control simply stays open (no loop).
  useEffect(() => {
    if (done && !revealed) {
      setExpanded(true);
      setRevealed(true);
    }
  }, [done, revealed]);

  const goReview = () => {
    // Provisional (no id yet): the run is still committing — nothing to review. Re-expand
    // and wait; the id lands in a moment and this becomes a live "Review" CTA.
    if (!pending.syncId) {
      setExpanded(true);
      return;
    }
    clear();
    router.push(`/review?sync_id=${encodeURIComponent(pending.syncId)}`);
  };
  const noun = `item${total === 1 ? '' : 's'}`;
  const progress = total > 0 ? ready / total : 0;

  return (
    <div ref={constraintsRef} className="pointer-events-none fixed inset-0 z-50">
      <motion.div
        drag
        dragMomentum={false}
        dragElastic={0.12}
        dragConstraints={constraintsRef}
        onDragEnd={persistPos}
        style={{ x, y, position: 'absolute', right: 16, bottom: 96, touchAction: 'none' }}
        className="pointer-events-auto"
      >
        <AnimatePresence mode="wait" initial={false}>
          {expanded ? (
            <motion.div
              key="expanded"
              initial={{ opacity: 0, scale: 0.8, x: 24 }}
              animate={
                done
                  ? { opacity: 1, x: 0, scale: [0.9, 1.08, 1] }
                  : { opacity: 1, scale: 1, x: 0 }
              }
              exit={{ opacity: 0, scale: 0.8, x: 24 }}
              // One-shot: the done keyframe has NO repeat, so the reveal pops once and holds.
              transition={{ duration: done ? 0.5 : 0.25, ease: 'easeOut' }}
              className="flex items-center gap-2"
            >
              <button
                type="button"
                onClick={goReview}
                aria-label={done ? `Review ${total} ${noun}` : `Tailoring ${total} ${noun}`}
                className="border-none bg-transparent p-0"
              >
                <ProcessingPill
                  state={done ? 'done' : 'running'}
                  progress={progress}
                  label={done ? `Review ${total} ${noun}` : `Tailoring ${total} ${noun}…`}
                />
              </button>
              {/* Always MINIMIZE to the side dock — never clear. A pending review (running or
                  ready) must stay reachable; it only clears when the user enters the review
                  (goReview). Losing it on ✕ would strand a ready review. */}
              <button
                type="button"
                onClick={() => setExpanded(false)}
                aria-label="Minimize"
                className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full active:scale-95"
                style={{
                  background: 'var(--tr-10)',
                  border: '1px solid var(--tr-20)',
                  color: M.faint,
                  transition: 'transform 120ms var(--ease-out)',
                }}
              >
                {done ? <X size={15} /> : <Minus size={15} />}
              </button>
            </motion.div>
          ) : (
            // Minimized dock: the §0 ProcessingPill disc. Tap to re-expand. When the review
            // is READY it glows mint (done ProcessingPill) so a minimized ready review still
            // reads as "ready", not "still working".
            <motion.button
              key="mini"
              type="button"
              onClick={() => setExpanded(true)}
              initial={{ opacity: 0, scale: 0.5 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: 0.5 }}
              transition={{ duration: 0.2, ease: 'easeOut' }}
              aria-label={done ? `Review ${total} ${noun} — expand` : `Tailoring ${total} ${noun} — expand`}
              className="pointer-events-auto border-none bg-transparent p-0"
            >
              {done ? (
                <ProcessingPill state="done" label={`Review ${total} ${noun}`} />
              ) : (
                <ProcessingPill minimized label={`Tailoring ${total} ${noun}…`} />
              )}
            </motion.button>
          )}
        </AnimatePresence>
      </motion.div>
    </div>
  );
}
