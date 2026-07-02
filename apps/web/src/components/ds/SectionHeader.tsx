'use client';

import React from 'react';
import { cn } from '@/lib/utils';

interface SectionHeaderProps {
  title: string;
  action?: string;
  onAction?: () => void;
  dark?: boolean;
  className?: string;
}

/** Section title row — heading on the left, optional action link on the right. */
export function SectionHeader({ title, action, onAction, dark = true, className }: SectionHeaderProps) {
  return (
    <div className={cn('flex items-center justify-between gap-3', className)}>
      <h2
        className="m-0 font-semibold"
        style={{
          fontFamily: 'var(--font-sans)',
          fontSize: 24,
          lineHeight: '30px',
          color: dark ? 'var(--pure-white)' : 'var(--text-strong)',
        }}
      >
        {title}
      </h2>
      {action && (
        <button
          type="button"
          onClick={onAction}
          className="border-none bg-transparent font-medium"
          style={{
            fontFamily: 'var(--font-sans)',
            fontSize: 14,
            color: dark ? 'rgba(255,255,255,0.8)' : 'var(--brand-teal)',
            cursor: onAction ? 'pointer' : 'default',
          }}
        >
          {action}
        </button>
      )}
    </div>
  );
}
