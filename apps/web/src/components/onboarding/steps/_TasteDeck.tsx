'use client';

import React, { useMemo, useRef, useState } from 'react';
import { Heart, X, Check } from 'lucide-react';
import {
  ARCHETYPES,
  ARCHETYPE_LABELS,
  type Archetype,
  type Department,
} from '@tailor/contracts';

import type { TasteSwipe } from '@/stores/useOnboardingStore';

/**
 * TasteDeck — the swipe screen (screen 4). Teaches Tailor's core gesture on a
 * light, static deck: image + swipe, nothing else (no edit/confirm/metadata/
 * polling — that lives in the review deck). Drag physics are copied verbatim from
 * review/page.tsx so the motion the user learns here is the motion they'll use to
 * review real imports.
 *
 * Each card = one archetype image. Single-department decks pull from that folder;
 * `both` / `gender_neutral` merge womens+mens (the only two on-disk image
 * departments, per ARCHETYPE_IMAGE_DEPARTMENTS) so the deck reflects the mixed
 * wardrobe. The store dedupes to a per-archetype verdict (last swipe wins), so the
 * 10 cards are the gesture reps while the ≤6 verdicts are what seeds taste.
 */

const DECK_SIZE = 10;
const SWIPE_COMMIT = 90; // release past this many px commits (like right / pass left)

interface DeckCard {
  archetype: Archetype;
  src: string;
}

type ImageDept = 'womens' | 'mens';

/** Distinct fallback hue per archetype — used only when an image fails to load. */
const FALLBACK_HUE: Record<Archetype, string> = {
  minimal: '#3a3f45',
  classic: '#3d3a33',
  street: '#2f3540',
  romantic_boho: '#43363c',
  sporty: '#2f4038',
  edgy: '#39323f',
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
      {/* Progress */}
      <div className="mb-3 flex items-center justify-between text-[13px]">
        <span style={{ color: 'rgba(255,255,255,0.6)' }}>
          {done ? `${deck.length} of ${deck.length}` : `${Math.min(index + 1, deck.length)} of ${deck.length}`}
        </span>
        <span style={{ color: 'var(--mint)' }}>{swipedCount} liked or passed</span>
      </div>

      {/* Card area */}
      <div className="relative flex-1" style={{ minHeight: 340 }}>
        {done ? (
          <div
            className="absolute inset-0 flex flex-col items-center justify-center gap-3 rounded-3xl"
            style={{ background: 'var(--tr-10)', border: '1px solid var(--tr-20)' }}
          >
            <span
              className="flex h-14 w-14 items-center justify-center rounded-full"
              style={{ background: 'var(--mint)' }}
            >
              <Check size={26} color="var(--brand-teal)" strokeWidth={3} />
            </span>
            <span className="text-[16px] font-semibold text-white">That&rsquo;s the gesture.</span>
            <span className="max-w-[240px] text-center text-[13px] text-white/60">
              You&rsquo;ll swipe just like this to review new items. Tap Continue.
            </span>
          </div>
        ) : (
          <>
            {/* Peeking cards behind for depth */}
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

            {/* Top card */}
            <div
              key={index}
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
              {/* Image (or a graceful gradient fallback if the asset is missing). */}
              <div className="relative flex-1" style={{ minHeight: 0 }}>
                {failed[current.src] ? (
                  <div
                    className="absolute inset-0 flex items-center justify-center"
                    style={{ background: FALLBACK_HUE[current.archetype] }}
                    aria-hidden
                  >
                    <span className="text-[15px] font-semibold text-white/70">
                      {ARCHETYPE_LABELS[current.archetype]}
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

                {/* Label chip */}
                <div
                  className="pointer-events-none absolute inset-x-0 bottom-0 px-4 pb-4 pt-10"
                  style={{ background: 'var(--grad-photo-fade)' }}
                >
                  <span className="text-[18px] font-bold text-white">
                    {ARCHETYPE_LABELS[current.archetype]}
                  </span>
                </div>
              </div>
            </div>
          </>
        )}
      </div>

      {/* Explicit controls (accessibility — never gesture-only). */}
      {!done ? (
        <div className="mt-4 flex items-center justify-center gap-4">
          <button
            type="button"
            onClick={() => commit(false)}
            aria-label={`Pass on ${ARCHETYPE_LABELS[current.archetype]}`}
            className="flex h-14 w-14 items-center justify-center rounded-full transition-transform active:scale-95"
            style={{ background: 'var(--tr-10)', border: '1px solid var(--tr-20)' }}
          >
            <X size={24} className="text-white" />
          </button>
          <button
            type="button"
            onClick={() => commit(true)}
            aria-label={`Like ${ARCHETYPE_LABELS[current.archetype]}`}
            className="flex h-16 w-16 items-center justify-center rounded-full transition-transform active:scale-95"
            style={{ background: 'var(--mint)' }}
          >
            <Heart size={26} color="var(--brand-teal)" fill="var(--brand-teal)" />
          </button>
        </div>
      ) : (
        <div className="mt-4 h-16" aria-hidden />
      )}
    </div>
  );
}
