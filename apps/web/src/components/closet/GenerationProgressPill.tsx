'use client';

/**
 * GenerationProgressPill — the add-photo "Preparing N → Review ready" affordance (Wave 2).
 *
 * After a photo commit, the backend generates a verified product card per staged
 * garment in the background (the run stays status='running' until it finishes). This
 * pill polls GET /gmail/ingest/status?sync_id= and reflects generation_ready /
 * generation_total. It is NON-BLOCKING and tappable throughout — tapping routes to the
 * review deck (scoped to this run), which itself streams the cards in. When the run
 * finishes (or every card is ready), the pill becomes a prominent "Review N items" CTA.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import { motion } from 'framer-motion';
import { ArrowRight, Sparkles } from 'lucide-react';

import { getIngestStatus } from '@/lib/api/gmail';

interface GenerationProgressPillProps {
  syncId: string;
  /** Candidates staged by the commit — the initial denominator until status reports one. */
  staged: number;
  /** Fired just before routing to the deck — e.g. the background-return pill clears its
   *  store entry so it doesn't linger once the user is reviewing. */
  onReview?: () => void;
}

export function GenerationProgressPill({ syncId, staged, onReview }: GenerationProgressPillProps) {
  const router = useRouter();
  const [ready, setReady] = useState(0);
  const [total, setTotal] = useState(staged);
  const [done, setDone] = useState(false);

  const mountedRef = useRef(true);
  const timersRef = useRef<ReturnType<typeof setTimeout>[]>([]);

  useEffect(() => {
    mountedRef.current = true;
    async function poll() {
      if (!mountedRef.current) return;
      try {
        const st = await getIngestStatus(syncId);
        if (!mountedRef.current) return;
        const gt = st.progress.generation_total || 0;
        const gr = st.progress.generation_ready || 0;
        const gf = st.progress.generation_failed || 0;
        setReady(gr);
        if (gt > 0) setTotal(gt);
        // Finished when the run leaves 'running', or every target has settled
        // (ready + failed === total). Either way the deck is ready to open.
        if (st.status !== 'running' || (gt > 0 && gr + gf >= gt)) {
          setDone(true);
          return; // stop polling
        }
      } catch {
        /* transient — keep polling */
      }
      timersRef.current.push(setTimeout(poll, 1500));
    }
    poll();
    return () => {
      mountedRef.current = false;
      timersRef.current.forEach(clearTimeout);
      timersRef.current = [];
    };
  }, [syncId]);

  const goReview = useCallback(() => {
    onReview?.();
    router.push(`/review?sync_id=${encodeURIComponent(syncId)}`);
  }, [router, syncId, onReview]);

  const noun = `item${total === 1 ? '' : 's'}`;

  return (
    <motion.button
      type="button"
      onClick={goReview}
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.25, ease: 'easeOut' }}
      className="inline-flex items-center gap-2.5 rounded-full font-semibold"
      aria-label={done ? `Review ${total} ${noun}` : `Tailoring ${total} ${noun}`}
      style={
        done
          ? {
              background: 'var(--mint)',
              color: 'var(--brand-teal)',
              padding: '12px 22px',
              fontSize: 15,
              boxShadow: '0 8px 24px rgba(75,226,214,0.3)',
            }
          : {
              background: 'var(--tr-10)',
              border: '1px solid var(--tr-20)',
              color: 'rgba(255,255,255,0.85)',
              padding: '11px 18px',
              fontSize: 14,
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
          <Sparkles size={15} style={{ opacity: 0.9 }} />
          {total > 0 && (
            <span className="tabular-nums" style={{ color: 'rgba(255,255,255,0.55)', fontSize: 12.5 }}>
              {ready}/{total}
            </span>
          )}
        </>
      )}
    </motion.button>
  );
}
