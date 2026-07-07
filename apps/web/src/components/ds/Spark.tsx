import React from 'react';

import { StylistMark } from './StylistMark';

/**
 * Spark = the Tailor AI mark (the hanger glyph), mint by default. Every AI
 * accent uses it, so the whole app shares one symbol — this replaces both the
 * old generic sparkle chip and the interim threaded-needle mark.
 */
export function Spark({ size = 15, style }: { size?: number; style?: React.CSSProperties }) {
  return (
    <span
      className="inline-flex shrink-0"
      style={{ color: 'var(--mint)', lineHeight: 0, ...style }}
      aria-hidden
    >
      <StylistMark size={size} />
    </span>
  );
}
