import React from 'react';

import { M } from '../materials';
import { Thinking } from './LottieMark';

/**
 * §0 · G10 — Swipe-deck loading: three cards breathe at rest (t2-deck-a/b/c)
 * while the next batch loads, with the Thinking mark on the top card.
 */
export function DeckLoading({
  w = 220,
  h = 280,
  label = 'Fetching your finds…',
}: {
  w?: number;
  h?: number;
  label?: string;
}) {
  const card = (anim: string, z: number, o: number) => (
    <div
      data-t2-anim
      className="absolute inset-0"
      style={{
        borderRadius: 24,
        background: 'linear-gradient(170deg, rgba(255,255,255,0.09), rgba(255,255,255,0.03))',
        border: '1px solid rgba(255,255,255,0.12)',
        boxShadow: '0 18px 40px -14px rgba(0,0,0,0.55)',
        zIndex: z,
        opacity: o,
        animation: `${anim} 2.6s var(--ease-in-out) infinite`,
      }}
      aria-hidden
    />
  );
  return (
    <div className="flex flex-col items-center" style={{ gap: 26 }}>
      <div className="relative" style={{ width: w, height: h }}>
        {card('t2-deck-a', 1, 0.5)}
        {card('t2-deck-b', 2, 0.75)}
        <div
          data-t2-anim
          className="absolute inset-0 flex items-center justify-center"
          style={{
            borderRadius: 24,
            background: 'linear-gradient(170deg, rgba(20,60,57,0.75), rgba(9,26,25,0.85))',
            border: '1px solid rgba(255,255,255,0.14)',
            boxShadow: '0 22px 48px -14px rgba(0,0,0,0.6)',
            zIndex: 3,
            animation: 't2-deck-c 2.6s var(--ease-in-out) infinite',
          }}
        >
          <Thinking size={64} />
        </div>
      </div>
      {label && <div style={{ color: M.faint, fontSize: 13.5 }}>{label}</div>}
    </div>
  );
}
