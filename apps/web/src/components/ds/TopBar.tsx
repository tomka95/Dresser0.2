'use client';

import React from 'react';
import { useRouter } from 'next/navigation';

import { Icon } from './Icon';
import { M } from './materials';

interface TopBarProps {
  title?: string;
  /** Optional context line under the title (12.5px, faint). */
  sub?: string;
  /** Custom back handler; defaults to router.back(). */
  onBack?: () => void;
  /** Right-side slot (e.g. an icon button or a "Save" action). */
  right?: React.ReactNode;
}

/**
 * §0 · G3 — TopBar for secondary screens: glass back chip · title (+ context
 * sub) · right action slot. The title ellipsizes instead of wrapping.
 */
export function TopBar({ title, sub, onBack, right }: TopBarProps) {
  const router = useRouter();
  return (
    <div className="flex items-center gap-3">
      <button
        type="button"
        aria-label="Back"
        onClick={onBack ?? (() => router.back())}
        className="flex shrink-0 items-center justify-center text-white active:scale-90"
        style={{
          width: 40,
          height: 40,
          ...M.glass(14),
          boxShadow: 'none',
          transition: 'transform 240ms var(--spring)',
        }}
      >
        <Icon name="ArrowChevronLeftMD" size={20} />
      </button>
      <div className="min-w-0 flex-1">
        {title && (
          <div
            className="overflow-hidden text-ellipsis whitespace-nowrap text-white"
            style={{ fontSize: 18, fontWeight: 650, letterSpacing: '-0.3px' }}
          >
            {title}
          </div>
        )}
        {sub && (
          <div style={{ color: M.faint, fontSize: 12.5, marginTop: 1 }}>{sub}</div>
        )}
      </div>
      <div className="flex shrink-0 items-center gap-2">{right}</div>
    </div>
  );
}
