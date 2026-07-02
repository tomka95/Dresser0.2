'use client';

import React from 'react';
import { useRouter } from 'next/navigation';
import { Icon } from './Icon';

interface TopBarProps {
  title?: string;
  /** Custom back handler; defaults to router.back(). */
  onBack?: () => void;
  /** Right-side slot (e.g. an icon button or a "Save" action). */
  right?: React.ReactNode;
}

/** Small back/header row for secondary screens: glass back circle · title · right slot. */
export function TopBar({ title, onBack, right }: TopBarProps) {
  const router = useRouter();
  return (
    <div className="relative flex min-h-[40px] items-center justify-between px-1.5">
      <button
        type="button"
        aria-label="Back"
        onClick={onBack ?? (() => router.back())}
        className="flex items-center justify-center rounded-full text-white transition-transform active:scale-90"
        style={{ width: 40, height: 40, border: '1px solid var(--tr-20)', background: 'rgba(0,0,0,0.28)' }}
      >
        <Icon name="ArrowChevronLeftMD" size={20} />
      </button>
      {title && <div className="text-[17px] font-semibold text-white">{title}</div>}
      <div className="flex h-10 w-10 items-center justify-center text-white">{right}</div>
    </div>
  );
}
