'use client';

import React from 'react';
import { cn } from '@/lib/utils';
import { M } from './materials';

export interface CategoryChipItem {
  id: string;
  label: string;
}

interface CategoryChipsProps {
  items: CategoryChipItem[];
  value: string;
  onChange?: (id: string) => void;
  /** Retained for API compatibility — the chip is always the dark-shell treatment now. */
  dark?: boolean;
  className?: string;
}

/** Selected chip — teal gradient fill, white label (§3 · Chip `on`). */
const ON_STYLE: React.CSSProperties = {
  background: 'linear-gradient(165deg, #10635c, #0a3633)',
  color: '#fff',
  border: '1px solid rgba(255,255,255,0.2)',
  boxShadow: 'inset 0 1px 0 rgba(255,255,255,0.14)',
};
/** Unselected chip — translucent white on the dark shell. */
const OFF_STYLE: React.CSSProperties = {
  background: 'rgba(255,255,255,0.07)',
  color: M.soft,
  border: '1px solid rgba(255,255,255,0.12)',
};

/**
 * Horizontal scrolling row of category filter chips (§3 · Chip). One selected
 * chip carries the teal gradient, the rest are muted translucent-white pills.
 * Controlled; keyboard-operable.
 */
export function CategoryChips({ items, value, onChange, className }: CategoryChipsProps) {
  return (
    <div className={cn('flex overflow-x-auto scrollbar-hide', className)} style={{ gap: 8, padding: '2px 0 4px' }}>
      {items.map((item) => {
        const on = item.id === value;
        return (
          <span
            key={item.id}
            role="button"
            tabIndex={0}
            aria-pressed={on}
            onClick={() => onChange?.(item.id)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                onChange?.(item.id);
              }
            }}
            className="inline-flex shrink-0 cursor-pointer select-none items-center whitespace-nowrap font-accent"
            style={{
              height: 30,
              padding: '0 13px',
              borderRadius: 999,
              fontSize: 12.5,
              fontWeight: 550,
              letterSpacing: '0.1px',
              ...(on ? ON_STYLE : OFF_STYLE),
            }}
          >
            {item.label}
          </span>
        );
      })}
    </div>
  );
}
