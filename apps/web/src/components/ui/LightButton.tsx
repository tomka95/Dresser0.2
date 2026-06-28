import React from 'react';
import { cn } from '@/lib/utils';

interface LightButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  fullWidth?: boolean;
  leftIcon?: React.ReactNode;
}

/**
 * The primary CTA on the dark app shell: a solid white pill with brand-teal text.
 * (shadcn Button is light-surface themed, so the dark UI uses this instead.)
 */
export const LightButton = React.forwardRef<HTMLButtonElement, LightButtonProps>(
  ({ className, fullWidth, leftIcon, children, style, ...props }, ref) => (
    <button
      ref={ref}
      className={cn(
        'inline-flex items-center justify-center gap-2 rounded-full font-semibold text-[15px] transition-transform active:scale-[0.98] disabled:opacity-60',
        fullWidth && 'w-full',
        className
      )}
      style={{ height: 50, background: '#ffffff', color: 'var(--brand-teal)', ...style }}
      {...props}
    >
      {leftIcon}
      {children}
    </button>
  )
);
LightButton.displayName = 'LightButton';
