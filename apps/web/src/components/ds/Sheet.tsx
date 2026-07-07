'use client';

import React, { useEffect } from 'react';
import { cn } from '@/lib/utils';

import { M } from './materials';

interface SheetProps {
  open: boolean;
  onClose: () => void;
  title?: string;
  sub?: string;
  children: React.ReactNode;
  /** 'dark' — unified deep-glass sheet (§0 surface). 'light' — white ingest drawer. */
  tone?: 'dark' | 'light';
}

/**
 * §0 · G8 — Unified bottom sheet. The dark tone is the redesign surface: a
 * deep-glass panel floating 8px off the edges, grab handle, 20px title,
 * t2-rise entrance. The light tone keeps the white AddItemDrawer styling.
 */
export function Sheet({ open, onClose, title, sub, children, tone = 'dark' }: SheetProps) {
  // Close on Escape.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  if (!open) return null;

  const dark = tone === 'dark';
  return (
    <div className="fixed inset-0 z-50 mx-auto w-full max-w-[430px]">
      {/* Dim overlay */}
      <button
        type="button"
        aria-label="Close"
        onClick={onClose}
        className="absolute inset-0 cursor-default border-none"
        style={{ background: 'rgba(0,0,0,0.55)', animation: 't2-fade 200ms var(--ease-out)' }}
      />
      {/* Sheet panel */}
      <div
        role="dialog"
        aria-modal="true"
        aria-label={title}
        data-t2-anim
        className={cn('absolute', dark ? 'bottom-2 left-2 right-2' : 'inset-x-0 bottom-0')}
        style={
          dark
            ? {
                ...M.deep(34),
                padding: '10px 22px 26px',
                animation: 't2-rise 420ms var(--ease-out) both',
              }
            : {
                background: '#fff',
                borderTopLeftRadius: 30,
                borderTopRightRadius: 30,
                padding: '20px 24px 34px',
                animation: 't2-rise 420ms var(--ease-out) both',
              }
        }
      >
        {/* Grab handle */}
        <div
          className="mx-auto rounded-full"
          style={{
            width: 40,
            height: 4.5,
            background: dark ? 'rgba(255,255,255,0.22)' : 'var(--grey)',
            margin: dark ? '4px auto 14px' : '0 auto 18px',
          }}
          aria-hidden
        />
        {(title || sub) && (
          <div style={{ marginBottom: 16, marginTop: 2 }}>
            {title && (
              <div
                style={{
                  color: dark ? '#fff' : 'var(--text-strong)',
                  fontSize: 20,
                  fontWeight: 650,
                  letterSpacing: '-0.4px',
                }}
              >
                {title}
              </div>
            )}
            {sub && (
              <div
                style={{
                  color: dark ? M.faint : 'var(--text-muted)',
                  fontSize: 13.5,
                  lineHeight: 1.5,
                  marginTop: 4,
                }}
              >
                {sub}
              </div>
            )}
          </div>
        )}
        {children}
      </div>
    </div>
  );
}

interface RadioRowProps {
  label: string;
  sub?: string;
  on?: boolean;
  first?: boolean;
  onSelect?: () => void;
}

/** Single radio row for dark bottom-sheet pickers. */
export function RadioRow({ label, sub, on = false, first = false, onSelect }: RadioRowProps) {
  return (
    <button
      type="button"
      onClick={onSelect}
      className="flex w-full cursor-pointer items-center gap-3 border-none bg-transparent px-1 py-[15px] text-left"
      style={{ borderTop: first ? 'none' : '1px solid var(--tr-10)' }}
    >
      <div className="flex-1">
        <div className={cn('text-[15.5px] text-white', on ? 'font-semibold' : 'font-medium')}>{label}</div>
        {sub && (
          <div className="mt-0.5 text-[12.5px]" style={{ color: 'rgba(255,255,255,0.5)' }}>
            {sub}
          </div>
        )}
      </div>
      <span
        className="flex items-center justify-center rounded-full"
        style={{ width: 22, height: 22, border: `2px solid ${on ? 'var(--mint)' : 'var(--tr-20)'}` }}
      >
        {on && <span className="rounded-full" style={{ width: 10, height: 10, background: 'var(--mint)' }} />}
      </span>
    </button>
  );
}
