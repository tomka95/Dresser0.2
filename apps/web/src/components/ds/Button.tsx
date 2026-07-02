'use client';

import React from 'react';
import { cn } from '@/lib/utils';

type Variant = 'primary' | 'secondary' | 'outline' | 'ghost' | 'light';
type Size = 'sm' | 'md' | 'lg';

interface DSButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  pill?: boolean;
  fullWidth?: boolean;
  leftIcon?: React.ReactNode;
  rightIcon?: React.ReactNode;
  loading?: boolean;
}

const SIZES: Record<Size, { height: number; fontSize: number; padding: string }> = {
  sm: { height: 38, fontSize: 14, padding: '0 16px' },
  md: { height: 50, fontSize: 16, padding: '0 24px' },
  lg: { height: 56, fontSize: 18, padding: '0 32px' },
};

const VARIANTS: Record<Variant, React.CSSProperties> = {
  primary: { background: 'var(--brand-teal)', color: 'var(--pure-white)', border: '1px solid transparent' },
  secondary: { background: 'var(--surface-sunken)', color: 'var(--text-strong)', border: '1px solid transparent' },
  outline: { background: 'transparent', color: 'var(--text-strong)', border: '1px solid var(--grey-dark-1)' },
  ghost: { background: 'transparent', color: 'var(--brand-teal)', border: '1px solid transparent' },
  light: { background: 'var(--pure-white)', color: 'var(--brand-teal)', border: '1px solid transparent' },
};

/**
 * Tailor design-system button. Deep-teal filled by default; `light` (white pill)
 * is the primary action on the dark glass shell. 50px tall, 10px radius
 * (or full pill), Inter Medium.
 */
export function DSButton({
  variant = 'primary',
  size = 'md',
  pill = false,
  fullWidth = false,
  leftIcon,
  rightIcon,
  loading = false,
  disabled,
  className,
  style,
  children,
  type = 'button',
  ...rest
}: DSButtonProps) {
  const s = SIZES[size];
  return (
    <button
      type={type}
      disabled={disabled || loading}
      className={cn(
        'inline-flex items-center justify-center gap-2 whitespace-nowrap font-medium leading-none',
        'transition-[filter,transform] duration-150 hover:brightness-[0.92] active:scale-[0.98]',
        'disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:brightness-100 disabled:active:scale-100',
        fullWidth && 'w-full',
        className,
      )}
      style={{
        height: s.height,
        padding: s.padding,
        fontSize: s.fontSize,
        fontFamily: 'var(--font-sans)',
        borderRadius: pill ? 9999 : 10,
        ...VARIANTS[variant],
        ...style,
      }}
      {...rest}
    >
      {loading ? (
        <span
          className="inline-block h-4 w-4 rounded-full border-2 border-current"
          style={{ borderTopColor: 'transparent', animation: 'tailor-spin 0.7s linear infinite' }}
        />
      ) : (
        leftIcon
      )}
      {children}
      {!loading && rightIcon}
    </button>
  );
}
