'use client';

import React from 'react';
import { cn } from '@/lib/utils';

export interface ContextMenuItem {
  id?: string;
  label?: string;
  icon?: React.ReactNode;
  tone?: 'danger';
  disabled?: boolean;
  divider?: boolean;
}

interface ContextMenuProps {
  items: ContextMenuItem[];
  onSelect?: (id: string) => void;
  className?: string;
  style?: React.CSSProperties;
}

/**
 * Contextual / overflow menu. Rounded white sheet of menu items; supports
 * icons, a destructive tone, and dividers (item `divider: true`).
 */
export function ContextMenu({ items, onSelect, className, style }: ContextMenuProps) {
  return (
    <div
      role="menu"
      className={cn('flex min-w-[200px] flex-col gap-0.5 p-1.5', className)}
      style={{
        background: 'var(--surface-card)',
        borderRadius: 10,
        boxShadow: 'var(--shadow-lg)',
        border: '1px solid rgba(0,0,0,0.1)',
        ...style,
      }}
    >
      {items.map((item, i) => {
        if (item.divider) {
          return <div key={`d${i}`} className="my-1 h-px" style={{ background: 'rgba(0,0,0,0.1)' }} />;
        }
        const danger = item.tone === 'danger';
        return (
          <button
            key={item.id || item.label}
            type="button"
            role="menuitem"
            disabled={item.disabled}
            onClick={() => onSelect?.(item.id || item.label || '')}
            className={cn(
              'flex w-full items-center gap-2.5 rounded-md border-none bg-transparent px-3 py-2.5 text-left font-medium transition-colors',
              item.disabled ? 'cursor-not-allowed opacity-40' : 'cursor-pointer hover:bg-[var(--surface-sunken)]',
            )}
            style={{
              fontFamily: 'var(--font-sans)',
              fontSize: 14,
              color: danger ? 'var(--danger)' : 'var(--text-body)',
            }}
          >
            {item.icon && <span className="flex shrink-0">{item.icon}</span>}
            <span className="flex-1">{item.label}</span>
          </button>
        );
      })}
    </div>
  );
}
