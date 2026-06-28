import React from 'react';
import { cn } from '@/lib/utils';

type GlassTint = 'frost' | 'ai' | 'scrim';

interface GlassCardProps extends React.HTMLAttributes<HTMLDivElement> {
  tint?: GlassTint;
  /** Inner padding in px (matches the design-system GlassCard `padding` prop). */
  padding?: number;
}

const tintStyle: Record<GlassTint, React.CSSProperties> = {
  frost: {
    background: 'var(--tr-10)',
    border: '1px solid var(--tr-20)',
    backdropFilter: 'blur(12px)',
    WebkitBackdropFilter: 'blur(12px)',
  },
  ai: {
    background: 'var(--grad-ai)',
    border: '1px solid var(--tr-20)',
    backdropFilter: 'blur(12px)',
    WebkitBackdropFilter: 'blur(12px)',
  },
  scrim: {
    background: 'rgba(0,0,0,0.28)',
    border: '1px solid var(--tr-10)',
    backdropFilter: 'blur(12px)',
    WebkitBackdropFilter: 'blur(12px)',
  },
};

/** Frosted glass card used across the dark app shell. */
export function GlassCard({ tint = 'frost', padding = 16, className, style, children, ...rest }: GlassCardProps) {
  return (
    <div
      className={cn('rounded-[24px] text-white', className)}
      style={{ ...tintStyle[tint], padding, ...style }}
      {...rest}
    >
      {children}
    </div>
  );
}
