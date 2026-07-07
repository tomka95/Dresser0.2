'use client';

import React, { useRef, useState } from 'react';

import { M } from '@/components/ds';

/**
 * FitSlider — the integer 1..5 fit slider (screen 3), restyled to the redesign
 * (§2 · O3). Each slider is its own glass card; an untouched slider stays visually
 * NEUTRAL (muted rail, dashed ghost thumb, "Slide to set") and writes nothing to
 * the store. Once touched it fills with a teal→mint gradient and a glowing mint
 * thumb.
 *
 * A tap-only / drag / keyboard slider (no typing). Fully accessible: role="slider"
 * + arrow/Home/End keys, and the whole track is a ≥44px pointer target.
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

  // Value read-out toward the leaning pole (e.g. "Fitted +2" / "Oversized +1"),
  // neutral at 3.
  const readout = () => {
    if (!touched) return 'Slide to set';
    if (shown === 3) return 'Balanced';
    const toward = shown < 3 ? minLabel : maxLabel;
    const steps = Math.abs(shown - 3);
    return `${toward} +${steps}`;
  };

  return (
    <div
      className="select-none"
      style={{
        padding: '18px 18px 20px',
        borderRadius: 22,
        background: 'rgba(255,255,255,0.06)',
        border: '1px solid rgba(255,255,255,0.11)',
      }}
    >
      {/* Header — label + value read-out */}
      <div className="mb-4 flex items-baseline justify-between">
        <span className="text-[15px] font-semibold" style={{ color: '#fff' }}>
          {label}
        </span>
        <span
          className="text-[12.5px] font-semibold"
          style={{ color: touched ? 'var(--mint)' : M.ghost }}
        >
          {readout()}
        </span>
      </div>

      {/* Track — the whole strip is the pointer target (touchAction:none so a drag
          never scrolls the page). Height gives a ≥44px vertical hit area. */}
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
        <div
          className="relative h-[5px] w-full rounded-full"
          style={{ background: 'rgba(255,255,255,0.12)' }}
        >
          {/* Filled portion — teal→mint gradient once touched, muted before */}
          <div
            className="absolute inset-y-0 left-0 rounded-full"
            style={{
              width: `${pct}%`,
              background: touched
                ? 'linear-gradient(90deg, #147f74, var(--mint))'
                : 'rgba(255,255,255,0.28)',
              transition: dragging ? 'none' : 'width 140ms var(--ease-out)',
            }}
          />
          {/* Ticks */}
          {[0, 1, 2, 3, 4].map((i) => (
            <span
              key={i}
              className="absolute top-1/2 rounded-full"
              style={{
                left: `${(i / 4) * 100}%`,
                width: 2.5,
                height: 2.5,
                marginLeft: i === 0 ? 0 : i === 4 ? -2.5 : -1.25,
                transform: 'translateY(-50%)',
                background: 'rgba(255,255,255,0.3)',
              }}
              aria-hidden
            />
          ))}
          {/* Thumb — glowing mint when touched, dashed ghost when neutral */}
          <div
            className="absolute top-1/2 rounded-full"
            style={{
              left: `${pct}%`,
              width: 26,
              height: 26,
              transform: 'translate(-50%, -50%)',
              background: touched ? 'var(--mint)' : 'rgba(255,255,255,0.14)',
              border: touched
                ? '2px solid rgba(255,255,255,0.9)'
                : '1.5px dashed rgba(255,255,255,0.4)',
              boxShadow: touched ? '0 4px 14px rgba(75,226,214,0.45)' : 'none',
              backdropFilter: 'blur(6px)',
              WebkitBackdropFilter: 'blur(6px)',
              transition: dragging ? 'none' : 'all 200ms var(--ease-out)',
            }}
            aria-hidden
          />
        </div>
      </div>

      {/* Pole labels */}
      <div className="mt-2.5 flex justify-between text-[11.5px]">
        <span style={{ color: touched && shown <= 2 ? 'var(--mint)' : M.faint }}>{minLabel}</span>
        <span style={{ color: touched && shown >= 4 ? 'var(--mint)' : M.faint }}>{maxLabel}</span>
      </div>
    </div>
  );
}
