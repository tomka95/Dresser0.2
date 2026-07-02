'use client';

/**
 * BackgroundTailorNotice — the "your review is ready" surface for users who chose to
 * tailor in the background (Wave 2, polished).
 *
 * Mounted once globally (AppShell). When a photo run is pending in the generation store
 * AND the user is browsing elsewhere, it shows a non-blocking control:
 *   - appears expanded ("Tailoring N…" / "Review N →"),
 *   - a few seconds later minimizes into a small floating circle docked on the side
 *     (tap → re-expands),
 *   - and the moment generation FINISHES it pops back open and pulses/glows to grab
 *     attention so the user notices their review is ready.
 *
 * Reuses useGenerationRunStatus (the shared poll) + the generation store; sync_id is
 * preserved throughout. Hidden on /review (already there) and /add-photo (the preparing
 * screen owns the pill), so only one poller is ever live.
 */
import { useEffect, useState } from 'react';
import { usePathname, useRouter } from 'next/navigation';
import { AnimatePresence, motion } from 'framer-motion';
import { ArrowRight, Minus, Sparkles, X } from 'lucide-react';

import { useGenerationStore, type PendingGeneration } from '@/stores/useGenerationStore';
import { useGenerationRunStatus } from './useGenerationRunStatus';

export function BackgroundTailorNotice() {
  const pathname = usePathname();
  const pending = useGenerationStore((s) => s.pending);
  const onOwnedScreen =
    pathname?.startsWith('/review') || pathname?.startsWith('/add-photo');

  return (
    <AnimatePresence>
      {pending && !onOwnedScreen && <NoticeInner key={pending.syncId} pending={pending} />}
    </AnimatePresence>
  );
}

function NoticeInner({ pending }: { pending: PendingGeneration }) {
  const router = useRouter();
  const clear = useGenerationStore((s) => s.clear);
  const { ready, total, done } = useGenerationRunStatus(pending.syncId, pending.staged);
  const [expanded, setExpanded] = useState(true);

  // Auto-minimize to the side dock a few seconds after appearing — but only while still
  // running (a finished run stays open so its attention animation is seen).
  useEffect(() => {
    if (done) return;
    const t = setTimeout(() => setExpanded(false), 4000);
    return () => clearTimeout(t);
  }, [done]);

  // Finished → pop back open (attention-grabbing, below).
  useEffect(() => {
    if (done) setExpanded(true);
  }, [done]);

  const goReview = () => {
    clear();
    router.push(`/review?sync_id=${encodeURIComponent(pending.syncId)}`);
  };
  const noun = `item${total === 1 ? '' : 's'}`;

  return (
    <div className="pointer-events-none fixed inset-x-0 bottom-24 z-50 flex justify-end px-4">
      <AnimatePresence mode="wait" initial={false}>
        {expanded ? (
          <motion.div
            key="expanded"
            initial={{ opacity: 0, scale: 0.8, x: 24 }}
            animate={
              done
                ? {
                    opacity: 1,
                    x: 0,
                    scale: [1, 1.06, 1],
                    boxShadow: [
                      '0 8px 24px rgba(75,226,214,0.25)',
                      '0 0 28px 4px rgba(75,226,214,0.65)',
                      '0 8px 24px rgba(75,226,214,0.25)',
                    ],
                  }
                : { opacity: 1, scale: 1, x: 0 }
            }
            exit={{ opacity: 0, scale: 0.8, x: 24 }}
            transition={
              done
                ? { duration: 1.3, repeat: Infinity, ease: 'easeInOut' }
                : { duration: 0.25, ease: 'easeOut' }
            }
            className="pointer-events-auto flex items-center gap-2 rounded-full"
          >
            <button
              type="button"
              onClick={goReview}
              aria-label={done ? `Review ${total} ${noun}` : `Tailoring ${total} ${noun}`}
              className="inline-flex items-center gap-2.5 rounded-full font-semibold"
              style={
                done
                  ? { background: 'var(--mint)', color: 'var(--brand-teal)', padding: '12px 22px', fontSize: 15 }
                  : {
                      background: 'var(--tr-10)',
                      border: '1px solid var(--tr-20)',
                      color: 'rgba(255,255,255,0.85)',
                      padding: '11px 18px',
                      fontSize: 14,
                      backdropFilter: 'blur(8px)',
                      WebkitBackdropFilter: 'blur(8px)',
                    }
              }
            >
              {done ? (
                <>
                  <Sparkles size={17} />
                  Review {total} {noun}
                  <ArrowRight size={17} />
                </>
              ) : (
                <>
                  <span
                    className="h-4 w-4 shrink-0 rounded-full"
                    style={{
                      border: '2px solid var(--tr-20)',
                      borderTopColor: 'var(--mint)',
                      animation: 'tailor-spin 0.8s linear infinite',
                    }}
                    aria-hidden
                  />
                  Tailoring {total} {noun}
                  {total > 0 && (
                    <span className="tabular-nums" style={{ color: 'rgba(255,255,255,0.55)', fontSize: 12.5 }}>
                      {ready}/{total}
                    </span>
                  )}
                </>
              )}
            </button>
            {/* Minimize while running (→ side dock); dismiss once done. */}
            <button
              type="button"
              onClick={() => (done ? clear() : setExpanded(false))}
              aria-label={done ? 'Dismiss' : 'Minimize'}
              className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full active:scale-95"
              style={{
                background: 'var(--tr-10)',
                border: '1px solid var(--tr-20)',
                color: 'rgba(255,255,255,0.7)',
                transition: 'transform 120ms var(--ease-out)',
              }}
            >
              {done ? <X size={15} /> : <Minus size={15} />}
            </button>
          </motion.div>
        ) : (
          // Minimized dock: a small floating circle on the side. Tap to re-expand.
          <motion.button
            key="mini"
            type="button"
            onClick={() => setExpanded(true)}
            initial={{ opacity: 0, scale: 0.5 }}
            animate={{ opacity: 1, scale: 1 }}
            exit={{ opacity: 0, scale: 0.5 }}
            transition={{ duration: 0.2, ease: 'easeOut' }}
            aria-label={`Tailoring ${total} ${noun} — expand`}
            className="pointer-events-auto flex h-12 w-12 items-center justify-center rounded-full"
            style={{
              background: 'var(--tr-10)',
              border: '1px solid var(--tr-20)',
              backdropFilter: 'blur(8px)',
              WebkitBackdropFilter: 'blur(8px)',
              boxShadow: '0 6px 18px rgba(0,0,0,0.4)',
            }}
          >
            <span
              className="h-4 w-4 rounded-full"
              style={{
                border: '2px solid var(--tr-20)',
                borderTopColor: 'var(--mint)',
                animation: 'tailor-spin 0.8s linear infinite',
              }}
              aria-hidden
            />
          </motion.button>
        )}
      </AnimatePresence>
    </div>
  );
}
