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
 *
 * Visuals: the §0 ProcessingPill — running shows the Thinking mark + progress bar,
 * done shows the mint glow. Wrapped in a button so the whole pill routes to /review.
 */
import { useCallback, useEffect, useRef } from 'react';
import { useRouter } from 'next/navigation';
import { motion } from 'framer-motion';

import { ProcessingPill } from '@/components/ds';
import { useGenerationRunStatus } from './useGenerationRunStatus';

interface GenerationProgressPillProps {
  syncId: string;
  /** Candidates staged by the commit — the initial denominator until status reports one. */
  staged: number;
  /** Fired just before routing to the deck — e.g. the background-return pill clears its
   *  store entry so it doesn't linger once the user is reviewing. */
  onReview?: () => void;
  /** Fired ONCE when the run finishes. The waiting (preparing) screen uses this to
   *  auto-advance to the deck without a tap; the away notice omits it (shows a CTA). */
  onDone?: () => void;
}

export function GenerationProgressPill({ syncId, staged, onReview, onDone }: GenerationProgressPillProps) {
  const router = useRouter();
  const { ready, total, done } = useGenerationRunStatus(syncId, staged);

  // Fire onDone exactly once when the run finishes (via a ref so an inline prop doesn't
  // re-trigger). The waiting screen uses it to auto-advance.
  const onDoneRef = useRef(onDone);
  onDoneRef.current = onDone;
  const doneFiredRef = useRef(false);
  useEffect(() => {
    if (done && !doneFiredRef.current) {
      doneFiredRef.current = true;
      onDoneRef.current?.();
    }
  }, [done]);

  const goReview = useCallback(() => {
    onReview?.();
    router.push(`/review?sync_id=${encodeURIComponent(syncId)}`);
  }, [router, syncId, onReview]);

  const noun = `item${total === 1 ? '' : 's'}`;
  const progress = total > 0 ? ready / total : 0;

  return (
    <motion.button
      type="button"
      onClick={goReview}
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.25, ease: 'easeOut' }}
      className="border-none bg-transparent p-0"
      aria-label={done ? `Review ${total} ${noun}` : `Tailoring ${total} ${noun}`}
    >
      <ProcessingPill
        state={done ? 'done' : 'running'}
        progress={progress}
        label={done ? `Review ${total} ${noun}` : `Tailoring ${total} ${noun}…`}
      />
    </motion.button>
  );
}
