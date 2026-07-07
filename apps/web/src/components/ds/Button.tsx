'use client';

import React from 'react';
import { cn } from '@/lib/utils';

import { M } from './materials';

/* ══════════════════════════════════════════════════════════════════════════
   ONE button system (§0 · G8). Pill radius everywhere, 6 variants, 4 sizes.
   Press = spring scale 0.965 + darken. `pending` swaps the label for brand
   dots with no layout shift. Mint is RESERVED for AI actions.
   ══════════════════════════════════════════════════════════════════════════ */

export type BtnVariant = 'primary' | 'mint' | 'glass' | 'ghost' | 'outline' | 'danger';
export type BtnSize = 'lg' | 'md' | 'sm' | 'xs';

const BTN_V: Record<BtnVariant, React.CSSProperties> = {
  primary: {
    background: 'linear-gradient(165deg, #10635c, #0a3633)',
    color: '#fff',
    border: '1px solid rgba(255,255,255,0.14)',
    boxShadow: 'inset 0 1px 0 rgba(255,255,255,0.16), 0 10px 24px -8px rgba(4,26,25,0.7)',
  },
  // Mint is reserved for AI actions ("Ask Tailor", compose, restyle).
  mint: {
    background: 'linear-gradient(165deg, #52e8dc, #2cc9bc)',
    color: '#06302d',
    border: '1px solid rgba(255,255,255,0.25)',
    boxShadow: 'inset 0 1px 0 rgba(255,255,255,0.45), 0 10px 26px -8px rgba(75,226,214,0.45)',
  },
  glass: {
    background: 'rgba(255,255,255,0.09)',
    color: '#fff',
    border: '1px solid rgba(255,255,255,0.15)',
    boxShadow: 'inset 0 1px 0 rgba(255,255,255,0.10)',
    backdropFilter: 'blur(10px)',
    WebkitBackdropFilter: 'blur(10px)',
  },
  ghost: {
    background: 'transparent',
    color: M.soft,
    border: '1px solid transparent',
  },
  outline: {
    background: 'transparent',
    color: '#fff',
    border: '1px solid rgba(255,255,255,0.22)',
  },
  danger: {
    background: 'rgba(251,44,54,0.14)',
    color: '#ff8087',
    border: '1px solid rgba(251,44,54,0.35)',
  },
};

const BTN_S: Record<BtnSize, { height: number; fontSize: number; padding: string }> = {
  lg: { height: 52, fontSize: 16, padding: '0 24px' },
  md: { height: 45, fontSize: 14.5, padding: '0 20px' },
  sm: { height: 36, fontSize: 13, padding: '0 15px' },
  xs: { height: 29, fontSize: 12, padding: '0 12px' },
};

/** Three brand dots — the pending state inside buttons (no layout shift). */
export function PendingDots({ dark = false }: { dark?: boolean }) {
  const dot = (delay: number) => (
    <span
      data-t2-anim
      className="inline-block rounded-full"
      style={{
        width: 5.5,
        height: 5.5,
        background: dark ? '#06302d' : '#fff',
        animation: `t2-typing 1.1s ${delay}s infinite`,
      }}
    />
  );
  return (
    <span className="inline-flex items-center" style={{ gap: 5 }} aria-hidden>
      {dot(0)}
      {dot(0.15)}
      {dot(0.3)}
    </span>
  );
}

export interface BtnProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: BtnVariant;
  size?: BtnSize;
  /** Leading icon slot. */
  icon?: React.ReactNode;
  fullWidth?: boolean;
  /** Replaces the label with brand dots and disables interaction. */
  pending?: boolean;
}

export function Btn({
  variant = 'primary',
  size = 'md',
  icon,
  fullWidth = false,
  pending = false,
  disabled,
  className,
  style,
  children,
  type = 'button',
  ...rest
}: BtnProps) {
  const v = BTN_V[variant];
  const s = BTN_S[size];
  return (
    <button
      type={type}
      disabled={disabled || pending}
      className={cn(
        'inline-flex items-center justify-center gap-2 whitespace-nowrap select-none',
        'enabled:active:scale-[0.965] enabled:active:brightness-90',
        'disabled:cursor-not-allowed disabled:opacity-[0.45]',
        fullWidth && 'flex w-full',
        className,
      )}
      style={{
        ...v,
        ...s,
        borderRadius: 999,
        fontWeight: 600,
        fontFamily: 'var(--font-sans)',
        letterSpacing: '-0.1px',
        transition: 'all 240ms var(--spring)',
        ...style,
      }}
      {...rest}
    >
      {pending ? (
        <PendingDots dark={variant === 'mint'} />
      ) : (
        <>
          {icon}
          {children}
        </>
      )}
    </button>
  );
}

/** Round icon button — glass disc; `on` = mint tint (selected), `danger` = red glyph. */
export interface RoundBtnProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  icon?: React.ReactNode;
  /** Diameter in px. */
  size?: number;
  /** Selected/toggled state — mint tint + border. */
  on?: boolean;
  danger?: boolean;
}

export function RoundBtn({
  icon,
  size = 40,
  on = false,
  danger = false,
  className,
  style,
  children,
  type = 'button',
  ...rest
}: RoundBtnProps) {
  return (
    <button
      type={type}
      className={cn(
        'inline-flex shrink-0 items-center justify-center rounded-full',
        'enabled:active:scale-[0.92]',
        className,
      )}
      style={{
        width: size,
        height: size,
        color: danger ? '#ff8087' : on ? 'var(--mint)' : '#fff',
        background: on ? 'rgba(75,226,214,0.14)' : 'rgba(255,255,255,0.09)',
        border: on ? '1px solid rgba(75,226,214,0.4)' : '1px solid rgba(255,255,255,0.14)',
        backdropFilter: 'blur(10px)',
        WebkitBackdropFilter: 'blur(10px)',
        transition: 'all 240ms var(--spring)',
        ...style,
      }}
      {...rest}
    >
      {icon}
      {children}
    </button>
  );
}

/* ══════════════════════════════════════════════════════════════════════════
   Legacy DSButton — thin adapter over Btn so every existing call site keeps
   compiling. Variant map: primary→primary, light (old white CTA on dark
   glass)→primary, secondary→glass, outline→outline, ghost→ghost. Mint stays
   reserved for AI actions, so nothing legacy maps to it. `pill` is a no-op
   (everything is a pill now).
   ══════════════════════════════════════════════════════════════════════════ */

type LegacyVariant = 'primary' | 'secondary' | 'outline' | 'ghost' | 'light';
type LegacySize = 'sm' | 'md' | 'lg';

const LEGACY_VARIANT: Record<LegacyVariant, BtnVariant> = {
  primary: 'primary',
  secondary: 'glass',
  outline: 'outline',
  ghost: 'ghost',
  light: 'primary',
};

// Old heights 38/50/56 → nearest new sizes 36/52/52.
const LEGACY_SIZE: Record<LegacySize, BtnSize> = {
  sm: 'sm',
  md: 'lg',
  lg: 'lg',
};

interface DSButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: LegacyVariant;
  size?: LegacySize;
  /** No-op — every button is a pill in the redesign. Kept for compatibility. */
  pill?: boolean;
  fullWidth?: boolean;
  leftIcon?: React.ReactNode;
  rightIcon?: React.ReactNode;
  loading?: boolean;
}

export function DSButton({
  variant = 'primary',
  size = 'md',
  pill = false,
  fullWidth = false,
  leftIcon,
  rightIcon,
  loading = false,
  children,
  ...rest
}: DSButtonProps) {
  // `pill` is an accepted no-op compat prop (everything is a pill now); consume
  // it so it isn't spread onto the DOM button and isn't flagged as unused.
  void pill;
  return (
    <Btn
      variant={LEGACY_VARIANT[variant]}
      size={LEGACY_SIZE[size]}
      icon={leftIcon}
      fullWidth={fullWidth}
      pending={loading}
      {...rest}
    >
      {children}
      {rightIcon}
    </Btn>
  );
}
