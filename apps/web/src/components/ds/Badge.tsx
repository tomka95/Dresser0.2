'use client';

import React from 'react';
import { cn } from '@/lib/utils';

type Variant = 'primary' | 'secondary' | 'outline' | 'default' | 'danger';

interface DSBadgeProps extends React.HTMLAttributes<HTMLSpanElement> {
  variant?: Variant;
  /** Convenience: true → primary (teal fill), false → default (muted). */
  selected?: boolean;
  interactive?: boolean;
  /** Dark-shell unselected treatment (translucent white fill, white text). */
  dark?: boolean;
}

const STYLES: Record<Variant, React.CSSProperties> = {
  primary: { background: 'var(--brand-teal)', color: 'var(--pure-white)', border: '1px solid transparent' },
  secondary: { background: 'var(--surface-sunken)', color: 'var(--text-strong)', border: '1px solid transparent' },
  outline: { background: 'transparent', color: 'var(--text-body)', border: '1px solid var(--grey)' },
  default: { background: 'transparent', color: 'var(--grey-dark-1)', border: '1px solid transparent' },
  danger: { background: 'var(--danger)', color: 'var(--pure-white)', border: '1px solid transparent' },
};

/**
 * Pill badge / category chip. `primary` (teal fill) is the selected state,
 * `default` is muted. DM Sans label, 30px pill radius.
 */
export function DSBadge({
  variant = 'default',
  selected,
  interactive = false,
  dark = false,
  className,
  style,
  children,
  ...rest
}: DSBadgeProps) {
  const resolved: Variant = selected === undefined ? variant : selected ? 'primary' : 'default';
  const darkUnselected =
    dark && resolved === 'default'
      ? { background: 'var(--tr-10)', color: 'var(--pure-white)' }
      : undefined;
  return (
    <span
      className={cn(
        'inline-flex select-none items-center justify-center gap-1.5 whitespace-nowrap font-accent font-medium',
        'transition-colors duration-150',
        interactive ? 'cursor-pointer' : 'cursor-default',
        className,
      )}
      style={{
        minHeight: 25,
        padding: '5px 15px',
        borderRadius: 30,
        fontSize: 14,
        lineHeight: '20px',
        letterSpacing: '0.2px',
        ...STYLES[resolved],
        ...darkUnselected,
        ...style,
      }}
      {...rest}
    >
      {children}
    </span>
  );
}
