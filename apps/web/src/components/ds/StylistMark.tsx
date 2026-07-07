import React from 'react';

interface StylistMarkProps {
  /** Square size in px (width = height). */
  size?: number;
  /** Needle-eye dot color (reads as the eye of the needle). */
  eye?: string;
  style?: React.CSSProperties;
  className?: string;
}

/**
 * The Tailor AI mark — a threaded needle. Every AI accent in the app uses this
 * one symbol (no generic sparkles anywhere). Needle body inherits currentColor;
 * the eye dot is tinted separately so it can read against the needle fill.
 */
export function StylistMark({ size = 24, eye = '#0a3633', style, className }: StylistMarkProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 48 48"
      fill="none"
      style={style}
      className={className}
      aria-hidden
      focusable={false}
    >
      {/* Needle body */}
      <path
        d="M11 38 L31.5 15 C 33 13.3, 35.6 13.2, 37.2 14.7 C 38.9 16.3, 38.8 18.9, 37.1 20.4 Z"
        fill="currentColor"
      />
      {/* Needle eye */}
      <circle cx="34" cy="17" r="1.5" fill={eye} />
      {/* Thread */}
      <path
        d="M33 13.5 C 27 6, 12.5 8, 11.5 17.5 C 11 23, 18.5 24, 20 17.5"
        stroke="currentColor"
        strokeWidth="2.6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
