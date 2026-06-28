import React from 'react';

/** AI spark glyph chip (mint ✦ on a faint disc). */
export function Spark({ size = 40 }: { size?: number }) {
  return (
    <span
      style={{
        width: size,
        height: size,
        borderRadius: '50%',
        background: 'rgba(255,255,255,0.12)',
        display: 'inline-flex',
        alignItems: 'center',
        justifyContent: 'center',
        color: 'var(--mint)',
        fontSize: size * 0.45,
        flexShrink: 0,
      }}
    >
      ✦
    </span>
  );
}
