'use client';

import React from 'react';
import { Heart } from 'lucide-react';
import { cn } from '@/lib/utils';

export interface ItemTileData {
  id: string;
  name: string;
  brand?: string | null;
  imageUrl?: string | null;
}

interface ItemTileProps {
  item: ItemTileData;
  faved?: boolean;
  onFav?: (id: string) => void;
  onClick?: (id: string) => void;
  size?: 'sm' | 'md';
}

const FALLBACK_IMG =
  'data:image/svg+xml;utf8,' +
  encodeURIComponent(
    "<svg xmlns='http://www.w3.org/2000/svg' width='300' height='400'><rect width='100%' height='100%' fill='%23333'/></svg>"
  );

/** Clothing item tile — 3:4 photo, name + uppercase brand, glass favourite button. */
export function ItemTile({ item, faved, onFav, onClick, size = 'md' }: ItemTileProps) {
  return (
    <div
      onClick={() => onClick?.(item.id)}
      className={cn(
        'relative rounded-2xl overflow-hidden aspect-[3/4]',
        onClick && 'cursor-pointer'
      )}
      style={{ background: 'rgba(255,255,255,0.06)', border: '1px solid rgba(255,255,255,0.08)' }}
    >
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src={item.imageUrl || FALLBACK_IMG}
        alt={item.name}
        loading="lazy"
        className="w-full h-full object-cover"
      />
      <div className="absolute inset-0" style={{ background: 'var(--grad-photo-fade)' }} />
      {onFav && (
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            onFav(item.id);
          }}
          aria-label={faved ? 'Unfavourite' : 'Favourite'}
          className="absolute top-2.5 right-2.5 w-8 h-8 rounded-full flex items-center justify-center"
          style={{
            border: '1px solid var(--tr-20)',
            background: 'rgba(0,0,0,0.28)',
            backdropFilter: 'blur(6px)',
            color: faved ? 'var(--mint)' : 'rgba(255,255,255,0.85)',
          }}
        >
          <Heart size={16} fill={faved ? 'currentColor' : 'none'} />
        </button>
      )}
      <div className="absolute left-3 right-3 bottom-2.5">
        <div
          className="text-white font-semibold leading-tight"
          style={{ fontSize: size === 'sm' ? 13 : 15 }}
        >
          {item.name}
        </div>
        {item.brand && (
          <div
            className="font-accent uppercase"
            style={{ color: 'rgba(255,255,255,0.62)', fontSize: 11, letterSpacing: '0.4px' }}
          >
            {item.brand}
          </div>
        )}
      </div>
    </div>
  );
}
