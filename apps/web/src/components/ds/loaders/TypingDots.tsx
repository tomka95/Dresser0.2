import React from 'react';

/**
 * §0 · G10 — Streaming/typing indicator: three dots on the shared wave cadence
 * (same rhythm as the pending-button dots).
 */
export function TypingDots({
  size = 6,
  color = 'var(--mint)',
  style,
}: {
  size?: number;
  color?: string;
  style?: React.CSSProperties;
}) {
  const dot = (delay: number) => (
    <span
      data-t2-anim
      className="inline-block rounded-full"
      style={{
        width: size,
        height: size,
        background: color,
        animation: `t2-typing 1.15s ${delay}s var(--ease-in-out) infinite`,
      }}
    />
  );
  return (
    <span className="inline-flex items-center" style={{ gap: size * 0.8, ...style }} aria-hidden>
      {dot(0)}
      {dot(0.16)}
      {dot(0.32)}
    </span>
  );
}
