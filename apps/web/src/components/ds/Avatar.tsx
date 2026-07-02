import React from 'react';
import { cn } from '@/lib/utils';

interface DSAvatarProps extends React.HTMLAttributes<HTMLSpanElement> {
  src?: string | null;
  alt?: string;
  name?: string;
  size?: number;
  ring?: boolean;
}

/** Round avatar. Teal fallback fill with initials, or an image when available. */
export function DSAvatar({ src, alt = '', name, size = 44, ring = false, className, style, ...rest }: DSAvatarProps) {
  const initials = name
    ? name
        .trim()
        .split(/\s+/)
        .slice(0, 2)
        .map((w) => w[0])
        .join('')
        .toUpperCase()
    : '';
  return (
    <span
      className={cn('inline-flex shrink-0 items-center justify-center overflow-hidden rounded-full font-semibold', className)}
      style={{
        width: size,
        height: size,
        background: 'var(--teal-600)',
        color: 'var(--pure-white)',
        fontFamily: 'var(--font-sans)',
        fontSize: size * 0.4,
        border: ring ? '3px solid var(--teal-600)' : 'none',
        boxShadow: ring ? '0 0 0 2px var(--pure-white)' : 'none',
        ...style,
      }}
      {...rest}
    >
      {src ? (
        /* eslint-disable-next-line @next/next/no-img-element */
        <img src={src} alt={alt} className="h-full w-full object-cover" />
      ) : (
        initials || null
      )}
    </span>
  );
}
