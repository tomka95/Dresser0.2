import { Search, SlidersHorizontal } from 'lucide-react';
import { Input } from '@/components/ui/input';

interface ClosetSearchBarProps {
  value: string;
  onChange: (value: string) => void;
}

export function ClosetSearchBar({ value, onChange }: ClosetSearchBarProps) {
  return (
    <div className="flex gap-3 mb-6">
      <div className="flex-1">
        <Input
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder="Search items..."
          startIcon={<Search className="w-4 h-4" />}
          className="bg-gray-100/10 border-none text-white placeholder:text-gray-400 h-12 rounded-2xl"
        />
      </div>
      <button className="w-12 h-12 rounded-full bg-gray-100/10 flex items-center justify-center text-white hover:bg-gray-100/20 transition-colors">
        <SlidersHorizontal className="w-5 h-5" />
      </button>
    </div>
  );
}
