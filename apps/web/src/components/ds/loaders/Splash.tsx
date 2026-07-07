import React from 'react';

import { M } from '../materials';
import { Mark, Thinking } from './LottieMark';

/**
 * §0 · G10 — Splash / route transition: the hanger mark draws itself on, over
 * the wordmark. Fills its nearest positioned ancestor.
 */
export function Splash({ hint }: { hint?: string }) {
  return (
    <div className="absolute inset-0 flex flex-col items-center justify-center" style={{ gap: 18 }}>
      <Mark size={120} />
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src="/tailor-logo.png"
        alt="Tailor"
        style={{ height: 30, mixBlendMode: 'screen', display: 'block' }}
      />
      {hint && <div style={{ color: M.ghost, fontSize: 12.5, marginTop: 2 }}>{hint}</div>}
    </div>
  );
}

/** Full-screen AI processing (outfit compose etc.). */
export function ThinkingScreen({
  title = 'Styling your look…',
  sub,
}: {
  title?: string;
  sub?: string;
}) {
  return (
    <div
      className="flex flex-col items-center justify-center text-center"
      style={{ gap: 6, padding: '46px 30px' }}
    >
      <Thinking size={128} />
      <div style={{ color: '#fff', fontSize: 17, fontWeight: 650, letterSpacing: '-0.3px', marginTop: 10 }}>
        {title}
      </div>
      {sub && <div style={{ color: M.faint, fontSize: 13, lineHeight: 1.5, maxWidth: 250 }}>{sub}</div>}
    </div>
  );
}
