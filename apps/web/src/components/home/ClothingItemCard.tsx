import { Heart } from 'lucide-react';
import { cn } from '@/lib/utils';
import type { ClosetItem } from '@tailor/contracts';
import Link from 'next/link';

import { ItemImage } from '@/components/ui/ItemImage';

interface ClothingItemCardProps {
  item: ClosetItem;
  className?: string;
}

export function ClothingItemCard({ item, className }: ClothingItemCardProps) {
  return (
    <Link href={`/closet/${item.id}`} className="block">
      <div
        className={cn(
          'relative aspect-[3/4] rounded-2xl overflow-hidden transition-transform hover:scale-[1.02]',
          className,
        )}
      >
        <button
          className="absolute top-3 right-3 z-10 w-[32px] h-[32px] rounded-full bg-black/20 border border-white/30 flex items-center justify-center hover:bg-black/30 transition-colors"
          onClick={(e) => {
            e.preventDefault();
            // TODO: Toggle favorite
          }}
        >
          <Heart className="w-5 h-5 text-white/80" />
        </button>

        {/* Shared image path. contain = whole garment; opaque neutral backing (no
            mix-blend, which was erasing neutral-background cutouts here). */}
        <ItemImage src={item.imageUrl} alt={item.name} fit="contain" emptyLabel={item.name} />
      </div>
    </Link>
  );
}
