import { Heart } from 'lucide-react';
import { cn } from '@/lib/utils';
import type { ClosetItem } from '@tailor/contracts';
import Link from 'next/link';

interface ClothingItemCardProps {
  item: ClosetItem;
  className?: string;
}

export function ClothingItemCard({ item, className }: ClothingItemCardProps) {
  // Mock background color logic based on Figma observation (some cards have colored bg)
  // In a real app, this might come from analysis or color extraction
  const bgColor = item.category === 'top' ? 'bg-[#C8A27C]' : 'bg-white';
  const textColor = item.category === 'top' ? 'text-white' : 'text-black';
  const heartColor = item.category === 'top' ? 'text-white/80' : 'text-gray-400';

  return (
    <Link href={`/closet/${item.id}`} className="block">
      <div 
        className={cn(
          "relative aspect-[3/4] rounded-2xl overflow-hidden p-3 transition-transform hover:scale-[1.02]",
          bgColor,
          className
        )}
      >
        <button 
          className="absolute top-3 right-3 z-10 w-[32px] h-[32px] rounded-full bg-black/10 border border-white/30 flex items-center justify-center hover:bg-black/15 transition-colors"
          onClick={(e) => {
            e.preventDefault();
            // TODO: Toggle favorite
          }}
        >
          <Heart className={cn("w-5 h-5", heartColor)} />
        </button>

        <div className="w-full h-full flex items-center justify-center">
            {item.imageUrl ? (
                <img 
                src={item.imageUrl} 
                alt={item.name} 
                className="w-full h-full object-contain mix-blend-multiply"
                />
            ) : (
                <div className={cn("text-sm font-medium opacity-50", textColor)}>
                    {item.name}
                </div>
            )}
        </div>
      </div>
    </Link>
  );
}
