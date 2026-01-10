import { ClosetItemCard } from './ClosetItemCard';
import type { ClosetItem } from '@tailor/contracts';

interface ClosetGridProps {
  items: ClosetItem[];
}

export function ClosetGrid({ items }: ClosetGridProps) {
  if (items.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-12 text-center">
        <div className="w-16 h-16 rounded-full bg-white/5 flex items-center justify-center mb-4">
          <span className="text-2xl">👕</span>
        </div>
        <h3 className="text-white font-medium text-lg mb-2">Your closet is empty</h3>
        <p className="text-white/50 text-sm max-w-[200px]">
          Tap the + button to add your first item
        </p>
      </div>
    );
  }

  return (
    <div className="grid grid-cols-2 gap-4 pb-32">
      {items.map((item) => (
        <ClosetItemCard key={item.id} item={item} />
      ))}
    </div>
  );
}
