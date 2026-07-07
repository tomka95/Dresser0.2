'use client';

import React from 'react';
import { cn } from '@/lib/utils';
import { ItemImage } from '@/components/ui/ItemImage';
import { Icon } from './Icon';

interface ItemTileProps {
  name: string;
  brand?: string;
  imageUrl?: string | null;
  faved?: boolean;
  onFav?: () => void;
  onClick?: () => void;
  size?: 'sm' | 'md';
  className?: string;
  /** Top-left overlay slot (e.g. a "Most versatile" chip in the bento grid). */
  badge?: React.ReactNode;
  /** Fixed pixel height. When omitted the tile keeps its 3:4 aspect ratio. */
  h?: number;
  style?: React.CSSProperties;
}

/**
 * Clothing item tile (§3 · Tile) — 20px-radius photo card, aspect 3:4, bottom
 * photo-fade gradient, name + UPPERCASE DM-Sans brand, glass favourite disc
 * top-right. The shared unit for the closet / home / search grids.
 */
export function ItemTile({
  name,
  brand,
  imageUrl,
  faved,
  onFav,
  onClick,
  size = 'md',
  className,
  badge,
  h,
  style,
}: ItemTileProps) {
  return (
    <div
      className={cn('relative overflow-hidden', onClick && 'cursor-pointer', className)}
      style={{
        borderRadius: 20,
        aspectRatio: h ? undefined : '3 / 4',
        height: h,
        background: 'rgba(255,255,255,0.05)',
        border: '1px solid rgba(255,255,255,0.09)',
        boxShadow: '0 10px 26px -10px rgba(0,0,0,0.5)',
        ...style,
      }}
      onClick={onClick}
      role={onClick ? 'button' : undefined}
      tabIndex={onClick ? 0 : undefined}
      onKeyDown={(e) => {
        if (onClick && (e.key === 'Enter' || e.key === ' ')) onClick();
      }}
    >
      <ItemImage src={imageUrl} alt={name} fit="cover" />
      <div
        className="pointer-events-none absolute inset-0"
        style={{
          background:
            'linear-gradient(to top, rgba(0,0,0,0.78) 0%, rgba(0,0,0,0.16) 46%, transparent 100%)',
        }}
        aria-hidden
      />
      {badge && <span className="absolute left-2.5 top-2.5">{badge}</span>}
      {onFav && (
        <button
          type="button"
          aria-label={faved ? 'Remove from favorites' : 'Add to favorites'}
          onClick={(e) => {
            e.stopPropagation();
            onFav();
          }}
          className="absolute flex items-center justify-center rounded-full transition-transform active:scale-90"
          style={{
            top: 9,
            right: 9,
            width: 31,
            height: 31,
            border: '1px solid rgba(255,255,255,0.2)',
            background: 'rgba(0,0,0,0.3)',
            backdropFilter: 'blur(8px)',
            WebkitBackdropFilter: 'blur(8px)',
            color: faved ? 'var(--mint)' : 'rgba(255,255,255,0.85)',
          }}
        >
          <Icon name="InterfaceHeart02" size={15} />
        </button>
      )}
      <div className="absolute" style={{ left: 13, right: 13, bottom: 11 }}>
        <div
          className={cn(
            'truncate font-semibold leading-tight text-white',
            size === 'sm' ? 'text-[13px]' : 'text-[14px]',
          )}
          style={{ letterSpacing: '-0.15px' }}
        >
          {name}
        </div>
        {brand && (
          <div
            className="truncate font-accent uppercase"
            style={{ color: 'rgba(255,255,255,0.6)', fontSize: 10.5, letterSpacing: '0.6px', marginTop: 2 }}
          >
            {brand}
          </div>
        )}
      </div>
    </div>
  );
}
