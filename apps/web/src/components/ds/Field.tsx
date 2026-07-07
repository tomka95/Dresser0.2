'use client';

import React, { useState } from 'react';
import { cn } from '@/lib/utils';

import { M } from './materials';

export interface FieldProps {
  label?: string;
  /** Leading icon slot — tinted mint on focus, red on error. */
  icon?: React.ReactNode;
  /** Trailing slot (e.g. a clear button or unit). */
  right?: React.ReactNode;
  value: string;
  onChange?: (value: string) => void;
  placeholder?: string;
  /** Error state; a string doubles as the message rendered under the field. */
  error?: boolean | string;
  multiline?: boolean;
  type?: string;
  disabled?: boolean;
  autoComplete?: string;
  inputMode?: React.HTMLAttributes<HTMLInputElement>['inputMode'];
  name?: string;
  id?: string;
  rows?: number;
  onFocus?: React.FocusEventHandler<HTMLInputElement | HTMLTextAreaElement>;
  onBlur?: React.FocusEventHandler<HTMLInputElement | HTMLTextAreaElement>;
  onKeyDown?: React.KeyboardEventHandler<HTMLInputElement | HTMLTextAreaElement>;
  className?: string;
}

/**
 * §0 — Input row: label above a translucent 49px glass box (16px radius) that
 * focuses mint (border + soft ring) and errors red. Wraps a real
 * <input>/<textarea> (controlled).
 */
export function Field({
  label,
  icon,
  right,
  value,
  onChange,
  placeholder,
  error = false,
  multiline = false,
  type = 'text',
  disabled = false,
  autoComplete,
  inputMode,
  name,
  id,
  rows = 3,
  onFocus,
  onBlur,
  onKeyDown,
  className,
}: FieldProps) {
  const [focus, setFocus] = useState(false);
  const hasError = Boolean(error);

  const border = hasError
    ? '1px solid rgba(251,44,54,0.55)'
    : focus
      ? '1px solid rgba(75,226,214,0.55)'
      : '1px solid rgba(255,255,255,0.13)';
  const boxShadow = focus
    ? '0 0 0 3px rgba(75,226,214,0.14), inset 0 1px 0 rgba(255,255,255,0.07)'
    : hasError
      ? '0 0 0 3px rgba(251,44,54,0.10)'
      : 'inset 0 1px 0 rgba(255,255,255,0.07)';

  const controlProps = {
    value,
    placeholder,
    disabled,
    autoComplete,
    name,
    id,
    onKeyDown,
    className: cn(
      'w-full flex-1 border-none bg-transparent text-white outline-none placeholder:text-white/40',
      disabled && 'opacity-60',
    ),
    style: {
      fontSize: 15,
      fontFamily: 'var(--font-sans)',
      lineHeight: 1.45,
    } as React.CSSProperties,
  };

  return (
    <div className={className}>
      {label && (
        <div
          style={{
            color: M.soft,
            fontSize: 12.5,
            fontWeight: 600,
            marginBottom: 7,
            letterSpacing: '0.01em',
          }}
        >
          {label}
        </div>
      )}
      <div
        className={cn('flex gap-2.5', multiline ? 'items-start' : 'items-center')}
        style={{
          minHeight: 49,
          padding: multiline ? '13px 17px' : '0 17px',
          borderRadius: 16,
          background: 'rgba(255,255,255,0.075)',
          border,
          boxShadow,
          transition: 'all 200ms var(--ease-out)',
        }}
      >
        {icon && (
          <span
            className="flex shrink-0"
            style={{ color: hasError ? '#ff8087' : focus ? 'var(--mint)' : M.faint }}
            aria-hidden
          >
            {icon}
          </span>
        )}
        {multiline ? (
          <textarea
            {...controlProps}
            rows={rows}
            onChange={(e) => onChange?.(e.target.value)}
            onFocus={(e) => {
              setFocus(true);
              onFocus?.(e);
            }}
            onBlur={(e) => {
              setFocus(false);
              onBlur?.(e);
            }}
            className={cn(controlProps.className, 'resize-none')}
          />
        ) : (
          <input
            {...controlProps}
            type={type}
            inputMode={inputMode}
            onChange={(e) => onChange?.(e.target.value)}
            onFocus={(e) => {
              setFocus(true);
              onFocus?.(e);
            }}
            onBlur={(e) => {
              setFocus(false);
              onBlur?.(e);
            }}
            style={{ ...controlProps.style, height: 47 }}
          />
        )}
        {right && <span className="flex shrink-0 items-center">{right}</span>}
      </div>
      {typeof error === 'string' && error && (
        <div style={{ color: '#ff8087', fontSize: 12, marginTop: 6 }}>{error}</div>
      )}
    </div>
  );
}
