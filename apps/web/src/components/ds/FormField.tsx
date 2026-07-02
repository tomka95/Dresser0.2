'use client';

import React from 'react';
import { cn } from '@/lib/utils';

interface FormFieldProps {
  label: string;
  value: string;
  onChange?: (value: string) => void;
  placeholder?: string;
  multiline?: boolean;
  type?: string;
  disabled?: boolean;
  className?: string;
}

/**
 * Labeled dark form field (in-app edit forms): muted label above a translucent
 * glass input, 14px radius, 50px tall (78px multiline).
 */
export function FormField({
  label,
  value,
  onChange,
  placeholder,
  multiline = false,
  type = 'text',
  disabled = false,
  className,
}: FormFieldProps) {
  const boxStyle: React.CSSProperties = {
    background: 'var(--tr-10)',
    border: '1px solid var(--tr-20)',
    borderRadius: 14,
    fontFamily: 'var(--font-sans)',
    fontSize: 15,
    lineHeight: 1.45,
    color: 'var(--pure-white)',
  };
  return (
    <div className={className}>
      <div
        className="mx-0.5 mb-[7px] font-semibold"
        style={{ color: 'rgba(255,255,255,0.6)', fontSize: 12.5, letterSpacing: '0.3px' }}
      >
        {label}
      </div>
      {multiline ? (
        <textarea
          value={value}
          onChange={(e) => onChange?.(e.target.value)}
          placeholder={placeholder}
          disabled={disabled}
          rows={3}
          className={cn('w-full resize-none outline-none placeholder:text-white/40', disabled && 'opacity-60')}
          style={{ ...boxStyle, minHeight: 78, padding: '13px 16px' }}
        />
      ) : (
        <input
          type={type}
          value={value}
          onChange={(e) => onChange?.(e.target.value)}
          placeholder={placeholder}
          disabled={disabled}
          className={cn('w-full outline-none placeholder:text-white/40', disabled && 'opacity-60')}
          style={{ ...boxStyle, height: 50, padding: '0 16px' }}
        />
      )}
    </div>
  );
}
