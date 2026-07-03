'use client';

import React, { useRef } from 'react';

/**
 * FitSlider — a branded discrete 1..5 slider (screen 3). Tap a tick, drag the thumb,
 * or arrow-key it. `value` is undefined until the user first touches it (so the step
 * can require a deliberate answer); the thumb parks at the neutral centre, dimmed,
 * until then. 3 = neutral. The filled portion is a brand-green→mint sweep so the
 * chosen amount reads at a glance.
 */
const STEPS = [1, 2, 3, 4, 5] as const;

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
  value: number | undefined;
  onChange: (v: number) => void;
}) {
  const trackRef = useRef<HTMLDivElement>(null);
  const draggingRef = useRef(false);
  const touched = value !== undefined;
  const shown = value ?? 3; // park at neutral before first touch
  const pct = ((shown - 1) / 4) * 100;

  function fromClientX(clientX: number) {
    const el = trackRef.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    const ratio = Math.min(1, Math.max(0, (clientX - r.left) / r.width));
    const next = Math.round(ratio * 4) + 1; // → 1..5
    if (next !== value) onChange(next);
  }

  function onDown(e: React.PointerEvent) {
    draggingRef.current = true;
    e.currentTarget.setPointerCapture?.(e.pointerId);
    fromClientX(e.clientX);
  }
  function onMove(e: React.PointerEvent) {
    if (draggingRef.current) fromClientX(e.clientX);
  }
  function onUp() {
    draggingRef.current = false;
  }
  function onKey(e: React.KeyboardEvent) {
    if (e.key === 'ArrowLeft' || e.key === 'ArrowDown') {
      e.preventDefault();
      onChange(Math.max(1, shown - 1));
    } else if (e.key === 'ArrowRight' || e.key === 'ArrowUp') {
      e.preventDefault();
      onChange(Math.min(5, shown + 1));
    }
  }

  return (
    <section className="flex flex-col gap-3">
      <h2 className="m-0 text-[15px] font-semibold text-white/90">{label}</h2>

      <div
        ref={trackRef}
        role="slider"
        tabIndex={0}
        aria-label={label}
        aria-valuemin={1}
        aria-valuemax={5}
        aria-valuenow={touched ? shown : undefined}
        aria-valuetext={touched ? `${shown} of 5` : 'Not set'}
        onPointerDown={onDown}
        onPointerMove={onMove}
        onPointerUp={onUp}
        onPointerCancel={onUp}
        onKeyDown={onKey}
        className="relative flex items-center outline-none"
        style={{ height: 44, cursor: 'pointer', touchAction: 'none' }}
      >
        {/* base track */}
        <div className="absolute left-0 right-0 rounded-full" style={{ height: 6, background: 'rgba(255,255,255,0.12)' }} />
        {/* filled portion */}
        <div
          className="absolute left-0 rounded-full transition-[width,opacity] duration-150"
          style={{
            height: 6,
            width: `${pct}%`,
            opacity: touched ? 1 : 0.35,
            background: 'linear-gradient(90deg, var(--brand-teal) 0%, var(--mint) 100%)',
          }}
        />
        {/* ticks */}
        {STEPS.map((n) => {
          const on = touched && n <= shown;
          return (
            <span
              key={n}
              aria-hidden
              className="absolute rounded-full"
              style={{
                left: `${((n - 1) / 4) * 100}%`,
                transform: 'translateX(-50%)',
                width: 6,
                height: 6,
                background: on ? 'var(--mint)' : 'rgba(255,255,255,0.28)',
              }}
            />
          );
        })}
        {/* thumb */}
        <span
          aria-hidden
          className="absolute rounded-full transition-[left,opacity] duration-150"
          style={{
            left: `${pct}%`,
            transform: 'translateX(-50%)',
            width: 26,
            height: 26,
            background: '#fff',
            opacity: touched ? 1 : 0.6,
            boxShadow: touched ? '0 0 0 3px rgba(75,226,214,0.5), 0 2px 6px rgba(0,0,0,0.4)' : '0 2px 6px rgba(0,0,0,0.4)',
          }}
        />
      </div>

      <div className="flex items-center justify-between text-[12.5px]">
        <span style={{ color: touched && shown < 3 ? 'var(--mint)' : 'rgba(255,255,255,0.5)' }}>{minLabel}</span>
        <span style={{ color: touched && shown > 3 ? 'var(--mint)' : 'rgba(255,255,255,0.5)' }}>{maxLabel}</span>
      </div>
    </section>
  );
}
