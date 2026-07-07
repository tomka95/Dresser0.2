'use client';

import React from 'react';
import { cn } from '@/lib/utils';
import { M } from './materials';

export interface ContextMenuItem {
  id?: string;
  label?: string;
  /** Optional second line under the label (12px, faint). */
  sub?: string;
  icon?: React.ReactNode;
  tone?: 'danger';
  disabled?: boolean;
  divider?: boolean;
  /** Hover/hold title (e.g. "Coming soon") for disabled honest actions. */
  title?: string;
}

interface ContextMenuProps {
  items: ContextMenuItem[];
  onSelect?: (id: string) => void;
  className?: string;
  style?: React.CSSProperties;
}

/**
 * Contextual / overflow menu (§3 · C3). Deep-glass rounded sheet of rows: each
 * row is a 36px rounded icon tile · label (+ optional sub) with a destructive
 * `danger` tone and hairline dividers (`divider: true`). Disabled rows dim and
 * expose their `title` (used to keep un-wired actions honest).
 */
export function ContextMenu({ items, onSelect, className, style }: ContextMenuProps) {
  return (
    <div
      role="menu"
      className={cn('flex min-w-[220px] flex-col', className)}
      style={{ ...M.deep(22), padding: '6px 12px', ...style }}
    >
      {items.map((item, i) => {
        if (item.divider) {
          return (
            <div
              key={`d${i}`}
              className="h-px"
              style={{ background: 'rgba(255,255,255,0.08)', margin: '4px 0' }}
              aria-hidden
            />
          );
        }
        const danger = item.tone === 'danger';
        return (
          <button
            key={item.id || item.label}
            type="button"
            role="menuitem"
            disabled={item.disabled}
            title={item.title}
            onClick={() => onSelect?.(item.id || item.label || '')}
            className={cn(
              'flex w-full items-center gap-3 border-none bg-transparent text-left',
              item.disabled ? 'cursor-not-allowed opacity-40' : 'cursor-pointer',
            )}
            style={{ padding: '11px 2px' }}
          >
            {item.icon && (
              <span
                className="flex shrink-0 items-center justify-center"
                style={{
                  width: 36,
                  height: 36,
                  borderRadius: 12,
                  background: danger ? 'rgba(251,44,54,0.11)' : 'rgba(255,255,255,0.08)',
                  border: '1px solid rgba(255,255,255,0.09)',
                  color: danger ? '#ff8087' : M.soft,
                }}
              >
                {item.icon}
              </span>
            )}
            <span className="min-w-0 flex-1">
              <span
                className="block truncate"
                style={{
                  color: danger ? '#ff8087' : '#fff',
                  fontSize: 14.5,
                  fontWeight: 550,
                  letterSpacing: '-0.1px',
                }}
              >
                {item.label}
              </span>
              {item.sub && (
                <span
                  className="mt-0.5 block"
                  style={{ color: M.faint, fontSize: 12, lineHeight: 1.4 }}
                >
                  {item.sub}
                </span>
              )}
            </span>
          </button>
        );
      })}
    </div>
  );
}
