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
}

/**
 * Clothing item tile — 3:4 photo, bottom fade, name + uppercase DM Sans brand,
 * glass heart button top-right. The closet/home/search grid unit.
 */
export function ItemTile({ name, brand, imageUrl, faved, onFav, onClick, size = 'md', className }: ItemTileProps) {
  return (
    <div
      className={cn('relative overflow-hidden rounded-2xl', onClick && 'cursor-pointer', className)}
      style={{ aspectRatio: '3 / 4', background: 'rgba(255,255,255,0.06)', border: '1px solid rgba(255,255,255,0.08)' }}
      onClick={onClick}
      role={onClick ? 'button' : undefined}
      tabIndex={onClick ? 0 : undefined}
      onKeyDown={(e) => {
        if (onClick && (e.key === 'Enter' || e.key === ' ')) onClick();
      }}
    >
      <ItemImage src={imageUrl} alt={name} fit="cover" />
      <div className="pointer-events-none absolute inset-0" style={{ background: 'var(--grad-photo-fade)' }} aria-hidden />
      {onFav && (
        <button
          type="button"
          aria-label={faved ? 'Remove from favorites' : 'Add to favorites'}
          onClick={(e) => {
            e.stopPropagation();
            onFav();
          }}
          className="absolute right-2.5 top-2.5 flex items-center justify-center rounded-full transition-transform active:scale-90"
          style={{
            width: 32,
            height: 32,
            border: '1px solid var(--tr-20)',
            background: 'rgba(0,0,0,0.28)',
            backdropFilter: 'blur(6px)',
            WebkitBackdropFilter: 'blur(6px)',
            color: faved ? 'var(--mint)' : 'rgba(255,255,255,0.85)',
          }}
        >
          <Icon name="InterfaceHeart02" size={16} />
        </button>
      )}
      <div className="absolute bottom-2.5 left-3 right-3">
        <div className={cn('font-semibold leading-tight text-white', size === 'sm' ? 'text-[13px]' : 'text-[15px]')}>
          {name}
        </div>
        {brand && (
          <div
            className="font-accent uppercase"
            style={{ color: 'rgba(255,255,255,0.62)', fontSize: 11, letterSpacing: '0.4px' }}
          >
            {brand}
          </div>
        )}
      </div>
    </div>
  );
}
