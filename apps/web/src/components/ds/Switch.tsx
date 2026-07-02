'use client';

import React from 'react';
import { cn } from '@/lib/utils';

interface DSSwitchProps {
  checked?: boolean;
  onChange?: (checked: boolean) => void;
  disabled?: boolean;
  className?: string;
  'aria-label'?: string;
}

/** iOS-style toggle. Teal when on — profile/settings rows. */
export function DSSwitch({ checked = false, onChange, disabled = false, className, ...rest }: DSSwitchProps) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      disabled={disabled}
      onClick={() => !disabled && onChange?.(!checked)}
      className={cn(
        'flex items-center rounded-full border-none p-[3px] transition-colors duration-250',
        checked ? 'justify-end' : 'justify-start',
        disabled ? 'cursor-not-allowed opacity-50' : 'cursor-pointer',
        className,
      )}
      style={{ width: 50, height: 30, background: checked ? 'var(--brand-teal)' : 'var(--grey)' }}
      {...rest}
    >
      <span
        className="rounded-full"
        style={{ width: 24, height: 24, background: 'var(--pure-white)', boxShadow: '0 1px 3px rgba(0,0,0,0.25)' }}
      />
    </button>
  );
}
