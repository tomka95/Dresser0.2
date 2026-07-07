'use client';

import React from 'react';
import { Check } from 'lucide-react';

import { M } from '@/components/ds';

/**
 * Shared tap-only controls for the onboarding screens — restyled to the redesign
 * material system (§2). ZERO free text: every answer is a tap.
 *
 * Selected language:
 *  - OptionCard — teal-gradient glass card with a mint check disc (single select).
 *  - Chip / Segmented — mint-tinted pill (multi/segmented select).
 * All targets clear the 44px minimum; aria roles are preserved so radiogroups,
 * pressed chips, and tab segments announce correctly.
 */

/**
 * Full-width single-select row (departments). One tap sets the value; the active
 * row fills with the teal glass gradient + mint ring and shows a mint check.
 * Rendered inside a role="radiogroup".
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
      className="flex w-full items-center gap-3.5 text-left enabled:active:scale-[0.99]"
      style={{
        minHeight: 66,
        padding: '18px 20px',
        borderRadius: 22,
        background: active
          ? 'linear-gradient(165deg, rgba(16,99,92,0.55), rgba(10,54,51,0.6))'
          : 'rgba(255,255,255,0.06)',
        border: active
          ? '1.5px solid rgba(75,226,214,0.55)'
          : '1px solid rgba(255,255,255,0.11)',
        boxShadow: active
          ? '0 12px 32px -10px rgba(10,84,80,0.6), inset 0 1px 0 rgba(255,255,255,0.14)'
          : 'inset 0 1px 0 rgba(255,255,255,0.06)',
        transition: `all 240ms var(--ease-out)`,
      }}
    >
      <span className="flex-1">
        <span
          className="block text-[17px] font-semibold leading-tight"
          style={{ color: '#fff', letterSpacing: '-0.3px' }}
        >
          {label}
        </span>
        {hint ? (
          <span className="mt-0.5 block text-[12.5px]" style={{ color: M.faint }}>
            {hint}
          </span>
        ) : null}
      </span>
      <span
        className="flex items-center justify-center rounded-full"
        style={{
          width: 26,
          height: 26,
          background: active ? 'var(--mint)' : 'transparent',
          border: active ? 'none' : '1.5px solid rgba(255,255,255,0.25)',
          color: 'var(--brand-teal)',
          flexShrink: 0,
        }}
        aria-hidden
      >
        {active ? <Check size={15} strokeWidth={3} /> : null}
      </span>
    </button>
  );
}

/**
 * Pill toggle chip (size values, occasions). `active` drives aria-pressed so
 * multi-select groups announce correctly. `icon` renders a leading glyph (e.g. a
 * check on selected occasions).
 */
export function Chip({
  active,
  onClick,
  icon,
  children,
}: {
  active: boolean;
  onClick: () => void;
  icon?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className="inline-flex items-center justify-center gap-1.5 rounded-full font-medium enabled:active:scale-[0.96]"
      style={{
        minHeight: 44,
        padding: '0 16px',
        fontSize: 13.5,
        fontFamily: 'var(--font-accent)',
        letterSpacing: '0.1px',
        whiteSpace: 'nowrap',
        transition: `all 200ms var(--ease-out)`,
        ...(active
          ? {
              background: 'linear-gradient(165deg, #10635c, #0a3633)',
              color: '#fff',
              border: '1px solid rgba(255,255,255,0.2)',
              boxShadow: 'inset 0 1px 0 rgba(255,255,255,0.14)',
            }
          : {
              background: 'rgba(255,255,255,0.07)',
              color: M.soft,
              border: '1px solid rgba(255,255,255,0.12)',
            }),
      }}
    >
      {icon}
      {children}
    </button>
  );
}

/**
 * Segmented control — a small system switcher (bottom letter/waist, shoe US/EU/UK,
 * unit switch). The active segment fills mint; the container is a single
 * translucent pill.
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
      className="inline-flex gap-1 rounded-full"
      style={{
        padding: 3.5,
        background: 'rgba(255,255,255,0.07)',
        border: '1px solid rgba(255,255,255,0.12)',
      }}
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
            className="flex-1 rounded-full font-semibold"
            style={{
              minHeight: 34,
              padding: '0 18px',
              fontSize: 13,
              background: on ? 'var(--mint)' : 'transparent',
              color: on ? 'var(--brand-teal)' : M.faint,
              transition: `all 200ms var(--ease-out)`,
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
      <div className="mb-2.5 flex items-baseline gap-1.5">
        <span
          className="text-[11px] font-semibold uppercase"
          style={{ letterSpacing: '0.13em', color: M.soft, fontFamily: 'var(--font-accent)' }}
        >
          {label}
        </span>
        {!required ? (
          <span
            className="text-[11px] font-medium normal-case"
            style={{ letterSpacing: 'normal', color: M.ghost }}
          >
            optional
          </span>
        ) : null}
      </div>
      {children}
    </div>
  );
}
