'use client';

import React, { useRef, useState } from 'react';

/**
 * FitSlider — the integer 1..5 silhouette slider (screen 3).
 *
 * A tap-only / drag / keyboard slider (no typing). Unset stays visually neutral
 * (thumb at 3, muted) until the user commits, so an untouched slider writes
 * nothing to the store. Fully accessible: role="slider" + arrow/Home/End keys,
 * and the whole track is a ≥44px pointer target.
 */
export function FitSlider({
  label,
  minLabel,
  maxLabel,
  value,
  onChange,
}: {
  label: string;
  minLabel: string;
  maxLabel: string;
  /** undefined = untouched (rendered neutral, not written to the store). */
  value: number | undefined;
  onChange: (next: number) => void;
}) {
  const trackRef = useRef<HTMLDivElement>(null);
  const [dragging, setDragging] = useState(false);
  const touched = value !== undefined;
  const shown = value ?? 3;
  const pct = ((shown - 1) / 4) * 100;

  const commitFromClientX = (clientX: number) => {
    const el = trackRef.current;
    if (!el) return;
    const rect = el.getBoundingClientRect();
    const t = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width));
    onChange(Math.round(t * 4) + 1); // 1..5
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    let next = shown;
    if (e.key === 'ArrowLeft' || e.key === 'ArrowDown') next = Math.max(1, shown - 1);
    else if (e.key === 'ArrowRight' || e.key === 'ArrowUp') next = Math.min(5, shown + 1);
    else if (e.key === 'Home') next = 1;
    else if (e.key === 'End') next = 5;
    else return;
    e.preventDefault();
    onChange(next);
  };

  return (
    <div className="select-none">
      <div className="mb-3 text-[15px] font-semibold text-white">{label}</div>

      {/* Track — the whole strip is the pointer target (touchAction:none so a drag
          never scrolls the page). Padding gives a ≥44px vertical hit area. */}
      <div
        ref={trackRef}
        role="slider"
        aria-label={label}
        aria-valuemin={1}
        aria-valuemax={5}
        aria-valuenow={shown}
        aria-valuetext={touched ? `${shown} of 5` : 'not set'}
        tabIndex={0}
        onKeyDown={onKeyDown}
        onPointerDown={(e) => {
          setDragging(true);
          e.currentTarget.setPointerCapture?.(e.pointerId);
          commitFromClientX(e.clientX);
        }}
        onPointerMove={(e) => {
          if (dragging) commitFromClientX(e.clientX);
        }}
        onPointerUp={() => setDragging(false)}
        onPointerCancel={() => setDragging(false)}
        className="relative flex cursor-pointer items-center outline-none"
        style={{ height: 44, touchAction: 'none' }}
      >
        {/* Rail */}
        <div className="relative h-1.5 w-full rounded-full" style={{ background: 'var(--tr-20)' }}>
          {/* Filled portion */}
          <div
            className="absolute inset-y-0 left-0 rounded-full"
            style={{
              width: `${pct}%`,
              background: touched ? 'var(--mint)' : 'rgba(255,255,255,0.28)',
              transition: dragging ? 'none' : 'width 140ms var(--ease-out)',
            }}
          />
          {/* Ticks */}
          {[0, 1, 2, 3, 4].map((i) => (
            <span
              key={i}
              className="absolute top-1/2 h-1 w-1 -translate-y-1/2 rounded-full"
              style={{
                left: `${(i / 4) * 100}%`,
                marginLeft: i === 0 ? 0 : i === 4 ? -4 : -2,
                background: 'rgba(255,255,255,0.35)',
              }}
              aria-hidden
            />
          ))}
          {/* Thumb */}
          <div
            className="absolute top-1/2 rounded-full"
            style={{
              left: `${pct}%`,
              width: 26,
              height: 26,
              transform: 'translate(-50%, -50%)',
              background: touched ? 'var(--mint)' : '#fff',
              boxShadow: '0 2px 8px rgba(0,0,0,0.4)',
              border: touched ? '2px solid var(--brand-teal)' : '2px solid rgba(0,0,0,0.08)',
              opacity: touched ? 1 : 0.85,
              transition: dragging ? 'none' : 'left 140ms var(--ease-out)',
            }}
            aria-hidden
          />
        </div>
      </div>

      {/* Pole labels */}
      <div className="mt-2 flex justify-between text-[12.5px]">
        <span style={{ color: touched && shown <= 2 ? 'var(--mint)' : 'rgba(255,255,255,0.55)' }}>
          {minLabel}
        </span>
        <span style={{ color: touched && shown >= 4 ? 'var(--mint)' : 'rgba(255,255,255,0.55)' }}>
          {maxLabel}
        </span>
      </div>
    </div>
  );
}
