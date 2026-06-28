'use client';

import React from 'react';

interface SwitchProps {
  checked: boolean;
  onCheckedChange?: (checked: boolean) => void;
  disabled?: boolean;
  'aria-label'?: string;
}

/** Pill toggle. Mint track when on. */
export function Switch({ checked, onCheckedChange, disabled, ...rest }: SwitchProps) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      disabled={disabled}
      onClick={() => onCheckedChange?.(!checked)}
      className="relative inline-flex items-center transition-colors disabled:opacity-50"
      style={{
        width: 44,
        height: 26,
        borderRadius: 999,
        background: checked ? 'var(--mint)' : 'rgba(255,255,255,0.2)',
        flexShrink: 0,
      }}
      {...rest}
    >
      <span
        className="block transition-transform"
        style={{
          width: 20,
          height: 20,
          borderRadius: '50%',
          background: '#fff',
          transform: checked ? 'translateX(21px)' : 'translateX(3px)',
          boxShadow: '0 1px 3px rgba(0,0,0,0.3)',
        }}
      />
    </button>
  );
}
