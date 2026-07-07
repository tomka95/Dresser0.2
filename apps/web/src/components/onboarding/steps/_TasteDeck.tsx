'use client';

import React, { useMemo, useRef, useState } from 'react';
import { Heart, X } from 'lucide-react';
import {
  ARCHETYPES,
  ARCHETYPE_LABELS,
  type Archetype,
  type Department,
} from '@tailor/contracts';

import { M, HangerImg, SuccessPop } from '@/components/ds';
import type { TasteSwipe } from '@/stores/useOnboardingStore';

/**
 * TasteDeck — the swipe screen (screen 4), restyled to the redesign deck language
 * (§2 · O4). Teaches Tailor's core gesture on a light, static deck: image + swipe,
 * nothing else (no edit/confirm/metadata/polling — that lives in the review deck).
 * Drag physics are copied verbatim from review/page.tsx so the motion the user
 * learns here is the motion they'll use to review real imports.
 *
 * Each card = one archetype image. Single-department decks pull from that folder;
 * `both` / `gender_neutral` merge womens+mens (the only two on-disk image
 * departments) so the deck reflects the mixed wardrobe. The store dedupes to a
 * per-archetype verdict (last swipe wins), so the 10 cards are the gesture reps
 * while the ≤6 verdicts are what seeds taste.
 *
 * Fails soft: when a card image 404s the card shows a hanger + "judge the word, or
 * skip" so the flow never dead-ends on a missing asset.
 */

const DECK_SIZE = 10;
const SWIPE_COMMIT = 90; // release past this many px commits (like right / pass left)

interface DeckCard {
  archetype: Archetype;
  src: string;
}

type ImageDept = 'womens' | 'mens';

/** One-line taste descriptor per archetype (shown under the card name). */
const ARCHETYPE_HINT: Record<Archetype, string> = {
  minimal: 'Clean lines, muted palette, no logos',
  classic: 'Timeless tailoring, quiet quality',
  street: 'Bold graphics, relaxed layers, sneakers',
  romantic_boho: 'Soft textures, flowing shapes, prints',
  sporty: 'Technical, easy, ready to move',
  edgy: 'Sharp contrast, statement pieces',
};

function buildDeck(dept: Department): DeckCard[] {
  const merged = dept === 'both' || dept === 'gender_neutral';
  const imgDepts: ImageDept[] = merged ? ['womens', 'mens'] : [dept as ImageDept];
  const cards: DeckCard[] = [];

  // Pass 1: image -1 for every archetype (department alternates when merged so
  // both are represented and every archetype appears at least once).
  ARCHETYPES.forEach((a, i) => {
    const d = imgDepts[i % imgDepts.length];
    cards.push({ archetype: a, src: `/images/archetypes/${d}/${a}-1.jpg` });
  });
  // Pass 2: image -2 (the other department when merged) until the deck is full.
  ARCHETYPES.forEach((a, i) => {
    if (cards.length >= DECK_SIZE) return;
    const d = imgDepts[(i + 1) % imgDepts.length];
    cards.push({ archetype: a, src: `/images/archetypes/${d}/${a}-2.jpg` });
  });

  return cards.slice(0, DECK_SIZE);
}

export function TasteDeck({
  department,
  onSwipe,
  swipedCount,
}: {
  department: Department;
  onSwipe: (swipe: TasteSwipe) => void;
  /** Distinct-archetype verdicts recorded so far (store dedupes) — for the counter. */
  swipedCount: number;
}) {
  const deck = useMemo(() => buildDeck(department), [department]);
  const [index, setIndex] = useState(0);
  const [drag, setDrag] = useState<{ x: number; dragging: boolean }>({ x: 0, dragging: false });
  const [failed, setFailed] = useState<Record<string, boolean>>({});
  const dragStartRef = useRef<number | null>(null);
  const dragXRef = useRef(0);

  const done = index >= deck.length;
  const current = deck[index];
  const baseRot = index % 2 === 0 ? -2 : 2;
  const acceptHint = Math.max(0, Math.min(1, drag.x / SWIPE_COMMIT));
  const rejectHint = Math.max(0, Math.min(1, -drag.x / SWIPE_COMMIT));

  function commit(liked: boolean) {
    if (!current) return;
    onSwipe({ archetype: current.archetype, liked });
    setIndex((i) => i + 1);
    // dragging:true resets the offset with transitions OFF so the next card lands
    // centered instantly instead of sliding in from the fling position.
    setDrag({ x: 0, dragging: true });
  }

  function onSwipeDown(e: React.PointerEvent) {
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
      commit(dx > 0);
    } else {
      setDrag({ x: 0, dragging: false }); // didn't cross the line → snap back (animated)
    }
  }

  return (
    <div className="flex flex-1 flex-col">
      {/* Progress — "This you?" · N of 10 · verdict counter */}
      <div className="mb-3 flex items-center justify-between text-[13px]">
        <span style={{ color: M.faint, fontVariantNumeric: 'tabular-nums' }}>
          {done
            ? `${deck.length} of ${deck.length}`
            : `${Math.min(index + 1, deck.length)} of ${deck.length}`}
        </span>
        <span style={{ color: 'var(--mint)' }}>{swipedCount} liked or passed</span>
      </div>

      {/* Card area */}
      <div className="relative flex-1" style={{ minHeight: 340 }}>
        {done ? (
          <div
            className="absolute inset-0 flex flex-col items-center justify-center gap-3 text-center"
            style={{ ...M.glass(28), padding: '0 26px' }}
          >
            <SuccessPop size={72} />
            <span className="mt-1 text-[16px] font-semibold text-white">That&rsquo;s the gesture.</span>
            <span className="max-w-[240px] text-[13px]" style={{ color: M.faint }}>
              You&rsquo;ll swipe just like this to review new items. Tap Continue.
            </span>
          </div>
        ) : (
          <>
            {/* Peeking cards behind for depth */}
            <div
              className="absolute rounded-[28px]"
              style={{
                inset: '18px 10px -6px',
                background: 'rgba(255,255,255,0.05)',
                border: '1px solid rgba(255,255,255,0.08)',
                transform: `rotate(${baseRot < 0 ? 4 : -4}deg)`,
              }}
              aria-hidden
            />
            <div
              className="absolute rounded-[28px]"
              style={{
                inset: '10px 4px 0',
                background: 'rgba(255,255,255,0.07)',
                border: '1px solid rgba(255,255,255,0.1)',
                transform: `rotate(${baseRot < 0 ? -2.5 : 2.5}deg)`,
              }}
              aria-hidden
            />

            {/* Top card */}
            <div
              key={index}
              className="absolute inset-0 overflow-hidden rounded-[28px]"
              onPointerDown={onSwipeDown}
              onPointerMove={onSwipeMove}
              onPointerUp={onSwipeEnd}
              onPointerCancel={onSwipeEnd}
              style={{
                background: '#15201e',
                border: '1px solid rgba(255,255,255,0.14)',
                boxShadow: '0 30px 60px -18px rgba(0,0,0,0.65)',
                transform: `translateX(${drag.x}px) rotate(${baseRot + drag.x * 0.04}deg)`,
                transition: drag.dragging ? 'none' : 'transform 200ms var(--ease-out)',
                cursor: 'grab',
                touchAction: 'none',
                userSelect: 'none',
              }}
            >
              {/* Image (or a graceful hanger fallback if the asset is missing). */}
              {failed[current.src] ? (
                <div
                  className="absolute inset-0 flex flex-col items-center justify-center gap-3"
                  style={{ background: 'linear-gradient(170deg, #12403c, #0a1f1d)' }}
                  aria-hidden
                >
                  <HangerImg
                    w={44}
                    className="opacity-50 [filter:brightness(3)_grayscale(1)]"
                  />
                  <span
                    className="max-w-[170px] text-center text-[12.5px] leading-relaxed"
                    style={{ color: M.faint }}
                  >
                    Image didn&rsquo;t load — judge the word, or skip
                  </span>
                </div>
              ) : (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={current.src}
                  alt={`${ARCHETYPE_LABELS[current.archetype]} style`}
                  draggable={false}
                  onError={() => setFailed((f) => ({ ...f, [current.src]: true }))}
                  className="absolute inset-0 h-full w-full object-cover"
                />
              )}

              {/* Legibility gradient — top-to-bottom */}
              <div
                className="pointer-events-none absolute inset-0"
                style={{
                  background:
                    'linear-gradient(to top, rgba(0,0,0,0.82), rgba(0,0,0,0.05) 46%)',
                }}
                aria-hidden
              />

              {/* Swipe intent overlays */}
              <div
                className="pointer-events-none absolute left-4 top-4 rounded-lg px-3 py-1 text-[13px] font-bold uppercase tracking-wide"
                style={{
                  color: 'var(--brand-teal)',
                  background: 'var(--mint)',
                  opacity: acceptHint,
                  transform: `rotate(-8deg) scale(${0.9 + acceptHint * 0.1})`,
                }}
                aria-hidden
              >
                Like
              </div>
              <div
                className="pointer-events-none absolute right-4 top-4 rounded-lg px-3 py-1 text-[13px] font-bold uppercase tracking-wide text-white"
                style={{
                  background: 'var(--danger)',
                  opacity: rejectHint,
                  transform: `rotate(8deg) scale(${0.9 + rejectHint * 0.1})`,
                }}
                aria-hidden
              >
                Pass
              </div>

              {/* Name + descriptor */}
              <div className="pointer-events-none absolute inset-x-0 bottom-0 px-[22px] pb-5">
                <div
                  className="text-[25px] font-bold text-white"
                  style={{ letterSpacing: '-0.5px' }}
                >
                  {ARCHETYPE_LABELS[current.archetype]}
                </div>
                <div className="mt-0.5 text-[13px]" style={{ color: M.soft }}>
                  {ARCHETYPE_HINT[current.archetype]}
                </div>
              </div>
            </div>
          </>
        )}
      </div>

      {/* Explicit controls (accessibility — never gesture-only). */}
      {!done ? (
        <div className="mt-4 flex items-center justify-center gap-[22px]">
          <button
            type="button"
            onClick={() => commit(false)}
            aria-label={`Pass on ${ARCHETYPE_LABELS[current.archetype]}`}
            className="flex items-center justify-center rounded-full transition-transform active:scale-95"
            style={{
              width: 60,
              height: 60,
              background: 'rgba(255,255,255,0.07)',
              border: '1px solid rgba(255,255,255,0.16)',
              backdropFilter: 'blur(12px)',
              WebkitBackdropFilter: 'blur(12px)',
              color: 'rgba(255,255,255,0.8)',
            }}
          >
            <X size={24} />
          </button>
          <span
            className="text-center text-[11.5px] leading-tight"
            style={{ width: 54, color: M.ghost }}
            aria-hidden
          >
            swipe either way
          </span>
          <button
            type="button"
            onClick={() => commit(true)}
            aria-label={`Like ${ARCHETYPE_LABELS[current.archetype]}`}
            className="flex items-center justify-center rounded-full transition-transform active:scale-95"
            style={{
              width: 60,
              height: 60,
              background: 'linear-gradient(165deg, #52e8dc, #2cc9bc)',
              border: '1px solid rgba(255,255,255,0.3)',
              boxShadow: '0 12px 30px -8px rgba(75,226,214,0.5)',
              color: 'var(--brand-teal)',
            }}
          >
            <Heart size={24} color="var(--brand-teal)" fill="var(--brand-teal)" />
          </button>
        </div>
      ) : (
        <div className="mt-4 h-[60px]" aria-hidden />
      )}
    </div>
  );
}
