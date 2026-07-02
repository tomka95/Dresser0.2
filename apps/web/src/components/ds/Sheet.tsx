'use client';

import React, { useEffect } from 'react';
import { cn } from '@/lib/utils';

interface SheetProps {
  open: boolean;
  onClose: () => void;
  title?: string;
  sub?: string;
  children: React.ReactNode;
  /** 'dark' — glass settings/picker sheet. 'light' — white ingest drawer. */
  tone?: 'dark' | 'light';
}

/**
 * Bottom sheet with dim overlay. Dark glass variant for pickers/menus
 * (settings, Gmail manage) and light variant for the AddItemDrawer.
 * 28–30px top radius, drag handle, slide-up entrance.
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
        style={{ background: 'rgba(0,0,0,0.55)', animation: 'tailor-fade-in 200ms var(--ease-out)' }}
      />
      {/* Sheet */}
      <div
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className="absolute inset-x-0 bottom-0"
        style={{
          animation: 'tailor-slide-up 300ms var(--ease-out)',
          ...(dark
            ? {
                background: 'rgba(24,26,27,0.96)',
                backdropFilter: 'blur(20px)',
                WebkitBackdropFilter: 'blur(20px)',
                borderTop: '1px solid var(--tr-20)',
                borderTopLeftRadius: 28,
                borderTopRightRadius: 28,
                padding: '14px 20px 30px',
                boxShadow: '0 -20px 50px rgba(0,0,0,0.5)',
              }
            : {
                background: '#fff',
                borderTopLeftRadius: 30,
                borderTopRightRadius: 30,
                padding: '20px 24px 34px',
              }),
        }}
      >
        {/* Drag handle */}
        <div
          className="mx-auto rounded-sm"
          style={{
            width: 40,
            height: 4,
            background: dark ? 'var(--tr-20)' : 'var(--grey)',
            marginBottom: dark ? 16 : 18,
          }}
          aria-hidden
        />
        {title && (
          <div
            className={cn('px-0.5 font-bold', dark ? 'text-white text-[18px]' : 'text-[21px]')}
            style={dark ? undefined : { color: 'var(--text-strong)' }}
          >
            {title}
          </div>
        )}
        {sub && (
          <div
            className="px-0.5 pt-0.5"
            style={{ fontSize: dark ? 13 : 14, color: dark ? 'rgba(255,255,255,0.55)' : 'var(--text-muted)' }}
          >
            {sub}
          </div>
        )}
        <div className={cn(title || sub ? 'mt-4' : undefined)}>{children}</div>
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
