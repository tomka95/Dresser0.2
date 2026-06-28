'use client';

import React from 'react';
import { DarkBadge } from './DarkBadge';

export interface CategoryChipItem {
  id: string;
  label: string;
}

interface CategoryChipsProps {
  items: CategoryChipItem[];
  value: string;
  onChange: (id: string) => void;
}

/** Horizontally scrollable category filter chips for the dark UI. */
export function CategoryChips({ items, value, onChange }: CategoryChipsProps) {
  return (
    <div className="flex gap-2 overflow-x-auto scrollbar-hide -mx-1 px-1">
      {items.map((it) => (
        <DarkBadge
          key={it.id}
          interactive
          selected={value === it.id}
          onClick={() => onChange(it.id)}
        >
          {it.label}
        </DarkBadge>
      ))}
    </div>
  );
}
