import Link from 'next/link';
import type { ClosetItem } from '@tailor/contracts';

import { ItemImage } from '@/components/ui/ItemImage';

interface ClosetItemCardProps {
  item: ClosetItem;
}

export function ClosetItemCard({ item }: ClosetItemCardProps) {
  return (
    <Link href={`/closet/${item.id}`} className="block group">
      <div className="relative aspect-[3/4] rounded-2xl overflow-hidden mb-2">
        {/* Shared, opaque-backed image render path (no backdrop bleed-through). */}
        <ItemImage
          src={item.imageUrl}
          alt={item.name}
          fit="cover"
          imgClassName="transition-transform duration-500 group-hover:scale-110"
        />

        {/* Gradient Overlay */}
        <div className="absolute inset-0 bg-gradient-to-t from-black/80 via-black/20 to-transparent opacity-80" />
        
        {/* Content Overlay */}
        <div className="absolute bottom-0 left-0 right-0 p-4">
          <h3 className="text-white font-semibold text-lg leading-tight mb-0.5 truncate">
            {item.name}
          </h3>
          <p className="text-white/60 text-xs font-medium uppercase tracking-wide">
            {item.category}
          </p>
        </div>
      </div>
    </Link>
  );
}
