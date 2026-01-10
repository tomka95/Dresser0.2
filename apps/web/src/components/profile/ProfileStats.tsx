import React from 'react';

interface ProfileStatsProps {
  itemsCount: number;
  outfitsCount: number;
}

export function ProfileStats({ itemsCount, outfitsCount }: ProfileStatsProps) {
  return (
    <div className="flex items-center justify-center w-full px-8 mb-8">
      {/* Items Stat */}
      <div className="flex flex-col items-center w-[100px]">
        <span className="text-3xl font-bold text-white mb-1">{itemsCount}</span>
        <span className="text-sm text-gray-400 font-light">Items</span>
      </div>

      {/* Divider */}
      <div className="w-[1px] h-[40px] bg-white/20 mx-8" />

      {/* Outfits Stat */}
      <div className="flex flex-col items-center w-[100px]">
        <span className="text-3xl font-bold text-white mb-1">{outfitsCount}</span>
        <span className="text-sm text-gray-400 font-light">Outfits</span>
      </div>
    </div>
  );
}
