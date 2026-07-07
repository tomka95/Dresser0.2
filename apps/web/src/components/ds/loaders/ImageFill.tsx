import React from 'react';

import { M } from '../materials';

/**
 * §0 · G10 — Image-fill placeholder while photos arrive: shimmer block with a
 * ghost hanger watermark, blur-up ready (swap in the real image on load).
 */
export function ImageFill({
  ratio = '3 / 4',
  radius = 20,
  label,
  style,
}: {
  ratio?: string;
  radius?: number;
  label?: string;
  style?: React.CSSProperties;
}) {
  return (
    <div
      className="t2-sk relative overflow-hidden"
      style={{
        aspectRatio: ratio,
        borderRadius: radius,
        border: '1px solid rgba(255,255,255,0.07)',
        ...style,
      }}
      aria-hidden
    >
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src="/9.png"
        alt=""
        className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2"
        style={{ width: '34%', opacity: 0.14, filter: 'grayscale(1) brightness(2.4)' }}
      />
      {label && (
        <span
          className="absolute bottom-3 left-0 right-0 text-center"
          style={{ color: M.ghost, fontSize: 10.5, fontFamily: 'ui-monospace, Menlo, monospace' }}
        >
          {label}
        </span>
      )}
    </div>
  );
}
