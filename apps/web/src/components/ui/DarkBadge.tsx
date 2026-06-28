'use client';

import React from 'react';
import { cn } from '@/lib/utils';

interface DarkBadgeProps extends React.HTMLAttributes<HTMLSpanElement> {
  selected?: boolean;
  interactive?: boolean;
  variant?: 'fill' | 'outline';
}

/** Pill badge / chip for the dark UI (filter scopes, style tags, status). */
export function DarkBadge({
  selected = false,
  interactive = false,
  variant = 'fill',
  className,
  style,
  children,
  ...rest
}: DarkBadgeProps) {
  const base: React.CSSProperties =
    variant === 'outline'
      ? { background: 'transparent', border: '1px solid var(--tr-20)', color: 'rgba(255,255,255,0.85)' }
      : selected
      ? { background: '#fff', border: '1px solid #fff', color: 'var(--brand-teal)' }
      : { background: 'var(--tr-10)', border: '1px solid var(--tr-20)', color: 'rgba(255,255,255,0.85)' };
  return (
    <span
      className={cn(
        'inline-flex items-center justify-center rounded-full font-accent text-[13px] font-medium px-3.5 py-2 whitespace-nowrap',
        interactive && 'cursor-pointer select-none',
        className
      )}
      style={{ ...base, letterSpacing: '0.2px', ...style }}
      {...rest}
    >
      {children}
    </span>
  );
}
