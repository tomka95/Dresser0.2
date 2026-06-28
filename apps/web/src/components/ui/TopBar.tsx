'use client';

import React from 'react';
import { useRouter } from 'next/navigation';
import { ChevronLeft } from 'lucide-react';

interface TopBarProps {
  title?: string;
  right?: React.ReactNode;
  /** Override the default router.back() behaviour. */
  onBack?: () => void;
}

/** Back/header row for secondary screens (glass circular back button). */
export function TopBar({ title, right, onBack }: TopBarProps) {
  const router = useRouter();
  const handleBack = onBack ?? (() => router.back());
  return (
    <div className="relative flex items-center justify-between px-1.5 min-h-[40px]">
      <button
        type="button"
        onClick={handleBack}
        aria-label="Back"
        className="w-10 h-10 rounded-full flex items-center justify-center text-white"
        style={{ border: '1px solid var(--tr-20)', background: 'rgba(0,0,0,0.28)' }}
      >
        <ChevronLeft size={20} />
      </button>
      {title && <div className="text-white text-[17px] font-semibold">{title}</div>}
      <div className="w-10 h-10 flex items-center justify-center text-white">{right}</div>
    </div>
  );
}
