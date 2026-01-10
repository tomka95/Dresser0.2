import Link from 'next/link';
import type { ClosetItem } from '@tailor/contracts';

interface ClosetItemCardProps {
  item: ClosetItem;
}

export function ClosetItemCard({ item }: ClosetItemCardProps) {
  return (
    <Link href={`/closet/${item.id}`} className="block group">
      <div className="relative aspect-[3/4] rounded-2xl overflow-hidden mb-2">
        {/* Background/Image */}
        {item.imageUrl ? (
          <img
            src={item.imageUrl}
            alt={item.name}
            className="w-full h-full object-cover transition-transform duration-500 group-hover:scale-110"
          />
        ) : (
          <div className="w-full h-full bg-white/5 flex items-center justify-center">
            <span className="text-white/40 text-sm">No Image</span>
          </div>
        )}
        
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
