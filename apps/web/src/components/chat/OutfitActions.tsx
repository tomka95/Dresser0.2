'use client';

import { useState } from 'react';
import { Check, CheckCircle2, ThumbsDown } from 'lucide-react';
import type { ChatOutfitPayload, OutfitReasonChip } from '@tailor/contracts';

import { Icon, Thinking } from '@/components/ds';
import { ItemImage } from '@/components/ui/ItemImage';
import { sendOutfitFeedback } from '@/lib/api/outfitFeedback';

import type { ClosetItemLite } from './types';

/** Reject reason chips shown when the user taps "Not for me". */
const REJECT_CHIPS: { chip: OutfitReasonChip; label: string; direction?: string }[] = [
  { chip: 'formality', label: 'Too dressy', direction: 'too_formal' },
  { chip: 'formality', label: 'Too casual', direction: 'too_casual' },
  { chip: 'color', label: 'Colors off' },
  { chip: 'fit', label: 'Fit' },
  { chip: 'weather', label: 'Wrong for weather' },
  { chip: 'not_my_style', label: 'Not my style' },
];

const chip = {
  fontSize: 11.5,
  height: 28,
  padding: '0 12px',
  borderRadius: 999,
  background: 'var(--tr-10)',
  border: '1px solid var(--tr-20)',
  color: 'rgba(255,255,255,0.85)',
} as const;

/**
 * Reject / modify(swap) / worn affordances on a composed outfit (Wave S3).
 * Feedback is fire-and-forget via sendOutfitFeedback; on failure we surface a
 * retry-able line rather than faking success. Hidden entirely in incognito
 * (the page never mounts this while incognito is on — zero-trace).
 */
export function OutfitActions({
  outfit,
  conversationId,
  closetItems,
}: {
  outfit: ChatOutfitPayload;
  conversationId?: string;
  closetItems: ClosetItemLite[];
}) {
  const [phase, setPhase] = useState<'idle' | 'reject' | 'swap'>('idle');
  const [swapSlot, setSwapSlot] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const itemIds = outfit.itemIds;
  if (itemIds.length === 0) return null;

  const react = async (body: Parameters<typeof sendOutfitFeedback>[0], label: string) => {
    if (busy) return;
    setBusy(true);
    const ack = await sendOutfitFeedback({ ...body, itemIds, conversationId });
    setBusy(false);
    setDone(ack ? label : "Couldn't save that — try again.");
  };

  if (done) {
    return (
      <div
        className="mt-2.5 flex items-center gap-1.5 text-[12px] font-semibold"
        style={{ color: 'var(--mint)', paddingLeft: 2 }}
      >
        <CheckCircle2 size={14} /> {done}
      </div>
    );
  }

  if (busy) {
    return (
      <div className="mt-2.5 flex items-center gap-2" style={{ paddingLeft: 2 }}>
        <Thinking size={20} />
        <span className="text-[11.5px]" style={{ color: 'rgba(255,255,255,0.55)' }}>
          Noting that…
        </span>
      </div>
    );
  }

  if (phase === 'swap') {
    return (
      <div className="mt-2.5">
        {!swapSlot ? (
          <>
            <div className="mb-2 text-[11px]" style={{ color: 'rgba(255,255,255,0.55)' }}>
              Swap which piece?
            </div>
            <div className="flex gap-2 overflow-x-auto scrollbar-hide">
              {Object.entries(outfit.slots).map(([slot, item]) => (
                <button
                  key={slot}
                  type="button"
                  onClick={() => setSwapSlot(slot)}
                  className="shrink-0 overflow-hidden rounded-[9px]"
                  style={{ width: 40, height: 48, border: '1px solid var(--tr-20)' }}
                  aria-label={`Swap ${item.name}`}
                >
                  <ItemImage src={item.imageUrl ?? undefined} alt={item.name} fit="cover" />
                </button>
              ))}
              <button type="button" style={chip} className="shrink-0" onClick={() => setPhase('idle')}>
                Cancel
              </button>
            </div>
          </>
        ) : (
          <>
            <div className="mb-2 text-[11px]" style={{ color: 'rgba(255,255,255,0.55)' }}>
              Pick a replacement for the {swapSlot}
            </div>
            <div className="grid grid-cols-4 gap-2" style={{ maxHeight: 220, overflowY: 'auto' }}>
              {closetItems.map((it) => (
                <button
                  key={it.id}
                  type="button"
                  disabled={it.id === outfit.slots[swapSlot]?.id}
                  onClick={() =>
                    react(
                      {
                        feedback: 'modify',
                        removedItemId: outfit.slots[swapSlot]?.id,
                        replacementItemId: it.id,
                        slot: swapSlot,
                      },
                      'Got it — I noted that swap.'
                    )
                  }
                  className="overflow-hidden rounded-[9px] disabled:opacity-30"
                  style={{ aspectRatio: '3/4', border: '1px solid var(--tr-20)' }}
                >
                  <ItemImage src={it.imageUrl ?? undefined} alt={it.name} fit="cover" />
                </button>
              ))}
            </div>
            <button type="button" style={chip} className="mt-2" onClick={() => setSwapSlot(null)}>
              Back
            </button>
          </>
        )}
      </div>
    );
  }

  if (phase === 'reject') {
    return (
      <div className="mt-2.5">
        <div className="mb-2 text-[11px]" style={{ color: 'rgba(255,255,255,0.55)' }}>
          What&rsquo;s off?
        </div>
        <div className="flex flex-wrap gap-1.5">
          {REJECT_CHIPS.map(({ chip: reason, label, direction }) => (
            <button
              key={label}
              type="button"
              style={chip}
              onClick={() =>
                react(
                  {
                    feedback: 'reject',
                    reasonChips: [reason],
                    directions: direction ? { formality: direction } : undefined,
                  },
                  "Thanks — I'll keep that in mind."
                )
              }
            >
              {label}
            </button>
          ))}
          <button type="button" style={chip} onClick={() => setPhase('idle')}>
            Cancel
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="mt-2.5 flex flex-wrap gap-1.5">
      <button
        type="button"
        style={{ ...chip, background: 'rgba(75,226,214,0.13)', border: '1px solid rgba(75,226,214,0.35)', color: 'var(--mint)' }}
        onClick={() => react({ feedback: 'worn' }, 'Nice — noted you wore it.')}
      >
        <span className="mr-1 inline-flex align-middle">
          <Check size={12} />
        </span>
        Wore it
      </button>
      <button type="button" style={chip} onClick={() => setPhase('swap')}>
        <span className="mr-1 inline-flex align-middle" style={{ color: 'var(--mint)' }}>
          <Icon name="ArrowArrowsReload01" size={12} />
        </span>
        Swap a piece
      </button>
      <button type="button" style={chip} onClick={() => setPhase('reject')}>
        <span className="mr-1 inline-flex align-middle">
          <ThumbsDown size={12} />
        </span>
        Not for me
      </button>
    </div>
  );
}
