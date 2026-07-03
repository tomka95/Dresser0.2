'use client';

import React from 'react';
import { Check } from 'lucide-react';

/**
 * Shared tap-only controls for the onboarding screens.
 *
 * ZERO free text — every answer is a tap. Selected state follows the existing
 * dark-glass language (settings/sizes): mint fill (--mint) + deep-teal text
 * (--brand-teal, #084B4D) when active, translucent white otherwise. All targets
 * clear the 44px minimum.
 */

const UNSELECTED: React.CSSProperties = {
  background: 'var(--tr-10)',
  border: '1px solid var(--tr-20)',
  color: '#fff',
};
const SELECTED: React.CSSProperties = {
  background: 'var(--mint)',
  border: '1px solid transparent',
  color: 'var(--brand-teal)',
};

/**
 * Full-width single-select row (departments). One tap sets the value; the active
 * row fills mint with a teal check. Rendered inside a role="radiogroup".
 */
export function OptionCard({
  active,
  onClick,
  label,
  hint,
}: {
  active: boolean;
  onClick: () => void;
  label: string;
  hint?: string;
}) {
  return (
    <button
      type="button"
      role="radio"
      aria-checked={active}
      onClick={onClick}
      className="flex w-full items-center gap-3 rounded-2xl px-4 text-left transition-colors"
      style={{ minHeight: 60, ...(active ? SELECTED : UNSELECTED) }}
    >
      <span className="flex-1">
        <span className="block text-[16px] font-semibold leading-tight">{label}</span>
        {hint ? (
          <span
            className="mt-0.5 block text-[12.5px]"
            style={{ color: active ? 'rgba(8,75,77,0.7)' : 'rgba(255,255,255,0.55)' }}
          >
            {hint}
          </span>
        ) : null}
      </span>
      <span
        className="flex h-6 w-6 items-center justify-center rounded-full"
        style={{
          background: active ? 'var(--brand-teal)' : 'transparent',
          border: active ? 'none' : '1.5px solid var(--tr-20)',
        }}
        aria-hidden
      >
        {active ? <Check size={15} color="var(--mint)" strokeWidth={3} /> : null}
      </span>
    </button>
  );
}

/**
 * Pill toggle chip (size values, occasions). `pressed` drives aria-pressed so
 * multi-select groups announce correctly to screen readers.
 */
export function Chip({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className="inline-flex items-center justify-center rounded-full px-4 text-[14.5px] font-medium transition-colors"
      style={{ minHeight: 44, ...(active ? SELECTED : UNSELECTED) }}
    >
      {children}
    </button>
  );
}

/**
 * Segmented control — a small system switcher (bottom letter/waist, shoe US/EU/UK).
 * The active segment fills mint; the container is a single translucent pill.
 */
export function Segmented<T extends string>({
  options,
  value,
  onChange,
  labelFor,
  ariaLabel,
}: {
  options: readonly T[];
  value: T;
  onChange: (next: T) => void;
  labelFor?: (opt: T) => string;
  ariaLabel?: string;
}) {
  return (
    <div
      role="tablist"
      aria-label={ariaLabel}
      className="flex gap-1 rounded-full p-1"
      style={{ background: 'var(--tr-10)', border: '1px solid var(--tr-20)' }}
    >
      {options.map((opt) => {
        const on = opt === value;
        return (
          <button
            key={opt}
            type="button"
            role="tab"
            aria-selected={on}
            onClick={() => onChange(opt)}
            className="flex-1 rounded-full text-[13.5px] font-semibold transition-colors"
            style={{
              minHeight: 36,
              background: on ? 'var(--mint)' : 'transparent',
              color: on ? 'var(--brand-teal)' : 'rgba(255,255,255,0.7)',
            }}
          >
            {labelFor ? labelFor(opt) : opt}
          </button>
        );
      })}
    </div>
  );
}

/**
 * Labeled group in the sizes screen. `required` marks the top/bottom fields that
 * gate Continue; optional fields read "optional" so nothing feels compulsory.
 */
export function FieldBlock({
  label,
  required,
  children,
}: {
  label: string;
  required?: boolean;
  children: React.ReactNode;
}) {
  return (
    <div>
      <div className="mb-2 flex items-baseline gap-1.5">
        <span className="text-[12px] font-semibold uppercase tracking-[0.5px] text-white/55">
          {label}
        </span>
        {!required ? (
          <span className="text-[11px] font-medium normal-case tracking-normal text-white/35">
            optional
          </span>
        ) : null}
      </div>
      {children}
    </div>
  );
}
