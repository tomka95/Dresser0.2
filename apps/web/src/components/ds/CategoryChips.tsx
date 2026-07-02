'use client';

import React from 'react';
import { cn } from '@/lib/utils';
import { DSBadge } from './Badge';

export interface CategoryChipItem {
  id: string;
  label: string;
}

interface CategoryChipsProps {
  items: CategoryChipItem[];
  value: string;
  onChange?: (id: string) => void;
  dark?: boolean;
  className?: string;
}

/**
 * Horizontal scrolling row of category filter chips. One selected chip (teal),
 * the rest muted (translucent white on the dark shell). Controlled.
 */
export function CategoryChips({ items, value, onChange, dark = true, className }: CategoryChipsProps) {
  return (
    <div className={cn('flex gap-[11px] overflow-x-auto pb-1 scrollbar-hide', className)}>
      {items.map((item) => (
        <DSBadge
          key={item.id}
          interactive
          dark={dark}
          selected={item.id === value}
          className="shrink-0"
          role="button"
          tabIndex={0}
          onClick={() => onChange?.(item.id)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' || e.key === ' ') onChange?.(item.id);
          }}
        >
          {item.label}
        </DSBadge>
      ))}
    </div>
  );
}
