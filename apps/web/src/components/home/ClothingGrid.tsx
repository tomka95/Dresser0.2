import type { ClosetItem } from '@tailor/contracts';
import { ClothingItemCard } from './ClothingItemCard';

interface ClothingGridProps {
  items: ClosetItem[];
}

export function ClothingGrid({ items }: ClothingGridProps) {
  return (
    <div className="grid grid-cols-2 gap-4 pb-24">
      {items.map((item) => (
        <ClothingItemCard key={item.id} item={item} />
      ))}
    </div>
  );
}
