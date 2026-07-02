import React from 'react';
import { cn } from '@/lib/utils';

type Tint = 'frost' | 'ai' | 'solid' | 'scrim';

interface GlassCardProps extends React.HTMLAttributes<HTMLDivElement> {
  tint?: Tint;
  /** Inner padding in px (design default 20). */
  padding?: number;
  /** Corner radius (design default 24 — app info cards). */
  radius?: number;
}

const TINTS: Record<Tint, React.CSSProperties> = {
  frost: {
    background: 'var(--grad-glass)',
    border: '1px solid var(--tr-20)',
    backdropFilter: 'blur(var(--blur-glass))',
    WebkitBackdropFilter: 'blur(var(--blur-glass))',
  },
  ai: {
    background: 'var(--grad-ai)',
    border: '1px solid var(--tr-20)',
    backdropFilter: 'blur(var(--blur-sm))',
    WebkitBackdropFilter: 'blur(var(--blur-sm))',
  },
  solid: { background: 'var(--teal-500)', border: '1px solid transparent' },
  scrim: {
    background: 'var(--scrim)',
    border: '1px solid var(--tr-10)',
    backdropFilter: 'blur(var(--blur-sm))',
    WebkitBackdropFilter: 'blur(var(--blur-sm))',
  },
};

/**
 * Frosted-glass card — the app's signature surface over the blurred-closet photo.
 * Translucent white fill, hairline border, backdrop blur, lifted shadow.
 * `tint` swaps to the AI-teal, solid-teal or scrim treatments.
 */
export function GlassCard({
  tint = 'frost',
  padding = 20,
  radius = 24,
  className,
  style,
  children,
  ...rest
}: GlassCardProps) {
  return (
    <div
      className={cn('box-border text-white', className)}
      style={{
        borderRadius: radius,
        padding,
        boxShadow: 'var(--shadow-lg)',
        ...TINTS[tint],
        ...style,
      }}
      {...rest}
    >
      {children}
    </div>
  );
}
