'use client';

import React from 'react';
import { Search } from 'lucide-react';

interface SearchBarDarkProps {
  value?: string;
  defaultValue?: string;
  onChange?: (value: string) => void;
  placeholder?: string;
}

/** Dark glass pill search input. */
export function SearchBarDark({ value, defaultValue, onChange, placeholder }: SearchBarDarkProps) {
  return (
    <div
      className="flex items-center gap-2.5 px-4"
      style={{
        height: 48,
        borderRadius: 999,
        background: 'var(--tr-10)',
        boxShadow: 'inset 0 0 0 1px var(--tr-20)',
      }}
    >
      <Search size={18} style={{ color: 'rgba(255,255,255,0.7)' }} />
      <input
        value={value}
        defaultValue={defaultValue}
        onChange={(e) => onChange?.(e.target.value)}
        placeholder={placeholder}
        className="flex-1 bg-transparent outline-none border-none text-white text-[15px] placeholder:text-white/45"
        style={{ fontFamily: 'var(--font-sans)' }}
      />
    </div>
  );
}
