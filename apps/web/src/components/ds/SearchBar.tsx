'use client';

import React from 'react';
import { cn } from '@/lib/utils';
import { Icon } from './Icon';

interface DSSearchBarProps extends Omit<React.InputHTMLAttributes<HTMLInputElement>, 'onChange'> {
  onChange?: (value: string) => void;
  /** Dark glass treatment (the in-app closet/home/search pattern). */
  dark?: boolean;
  containerClassName?: string;
}

/**
 * Pill-shaped search field pre-wired with the magnifying-glass icon.
 * Dark variant: translucent white fill + inset hairline over the photo shell.
 */
export function DSSearchBar({
  onChange,
  dark = true,
  placeholder = 'Search',
  containerClassName,
  className,
  ...rest
}: DSSearchBarProps) {
  return (
    <div
      className={cn('flex items-center gap-3 rounded-full px-[15px]', containerClassName)}
      style={
        dark
          ? { height: 45, background: 'var(--tr-10)', boxShadow: 'inset 0 0 0 1px var(--tr-20)' }
          : { height: 45, background: 'var(--surface-card)', boxShadow: 'inset 0 0 0 1px var(--grey)' }
      }
    >
      <span className="flex shrink-0" style={{ color: dark ? 'rgba(255,255,255,0.6)' : 'var(--text-faint)' }}>
        <Icon name="IconSearch" size={18} />
      </span>
      <input
        type="search"
        placeholder={placeholder}
        onChange={(e) => onChange?.(e.target.value)}
        className={cn(
          'min-w-0 flex-1 border-none bg-transparent outline-none',
          '[&::-webkit-search-cancel-button]:hidden',
          className,
        )}
        style={{
          fontFamily: 'var(--font-sans)',
          fontSize: 14,
          color: dark ? 'var(--pure-white)' : 'var(--text-strong)',
        }}
        {...rest}
      />
    </div>
  );
}
