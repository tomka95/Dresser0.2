import React from 'react';

/**
 * Confidence cue. Mint dot = confident, amber dot = low (< 0.7) / needs review.
 * `conf` is 0..1.
 */
export function ConfidenceDot({ conf }: { conf: number }) {
  const low = conf < 0.7;
  return (
    <span
      title={`${Math.round(conf * 100)}% confidence`}
      style={{
        width: 8,
        height: 8,
        borderRadius: '50%',
        flexShrink: 0,
        display: 'inline-block',
        background: low ? 'var(--amber)' : 'var(--mint)',
        boxShadow: low ? '0 0 0 3px rgba(240,162,59,0.18)' : '0 0 0 3px rgba(75,226,214,0.16)',
      }}
    />
  );
}
