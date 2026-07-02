'use client';

/**
 * BackgroundTailorNotice — the "your review is ready" surface for users who chose to
 * tailor in the background (Wave 2).
 *
 * Mounted once globally (AppShell). When a photo run is pending in the generation store
 * AND the user is browsing elsewhere, this floats a non-blocking, dismissible pill:
 * subtle "Tailoring N items…" while the run is still going, then a prominent
 * "Review N items →" the moment it finishes — tap to open the run-scoped deck. It's an
 * option, never forced (the user opted to skip the wait); it can be dismissed.
 *
 * It reuses the exact GenerationProgressPill polling machinery, and deliberately does
 * NOT auto-advance (no onDone) — auto-advance is only for someone still WAITING on the
 * preparing screen. Hidden on /review (already there) and /add-photo (the preparing
 * screen owns the pill there), so only one poller is ever live.
 */
import { usePathname } from 'next/navigation';
import { AnimatePresence, motion } from 'framer-motion';
import { X } from 'lucide-react';

import { useGenerationStore } from '@/stores/useGenerationStore';
import { GenerationProgressPill } from './GenerationProgressPill';

export function BackgroundTailorNotice() {
  const pathname = usePathname();
  const pending = useGenerationStore((s) => s.pending);
  const clear = useGenerationStore((s) => s.clear);

  // The preparing screen (/add-photo) and the deck (/review) own the flow themselves.
  const onOwnedScreen =
    pathname?.startsWith('/review') || pathname?.startsWith('/add-photo');
  const show = Boolean(pending) && !onOwnedScreen;

  return (
    <AnimatePresence>
      {show && pending && (
        <motion.div
          key={pending.syncId}
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: 16 }}
          transition={{ duration: 0.25, ease: 'easeOut' }}
          className="pointer-events-none fixed inset-x-0 bottom-24 z-50 flex justify-center px-4"
        >
          <div className="pointer-events-auto flex items-center gap-2">
            {/* Same pill; tapping routes to the deck. onReview clears the stash so it
                doesn't linger once the user is reviewing. NO onDone → shows the CTA
                rather than auto-navigating. */}
            <GenerationProgressPill
              syncId={pending.syncId}
              staged={pending.staged}
              onReview={clear}
            />
            <button
              type="button"
              onClick={clear}
              aria-label="Dismiss"
              className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full active:scale-95"
              style={{
                background: 'var(--tr-10)',
                border: '1px solid var(--tr-20)',
                color: 'rgba(255,255,255,0.7)',
                transition: 'transform 120ms var(--ease-out)',
              }}
            >
              <X size={15} />
            </button>
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
