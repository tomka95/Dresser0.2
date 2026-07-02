import React from 'react';

/** AI spark glyph chip — the single mint ✦ accent allowed by the design language. */
export function Spark({ size = 40 }: { size?: number }) {
  return (
    <span
      className="inline-flex shrink-0 items-center justify-center rounded-full"
      style={{
        width: size,
        height: size,
        background: 'rgba(255,255,255,0.12)',
        color: 'var(--mint)',
        fontSize: size * 0.45,
      }}
      aria-hidden
    >
      ✦
    </span>
  );
}
