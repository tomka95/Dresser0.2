import React from 'react';
import { ChevronRight } from 'lucide-react';

interface StylePreferencesCardProps {
  favoriteStyles: string[];
  colorPreferences: string[];
}

export function StylePreferencesCard({ favoriteStyles, colorPreferences }: StylePreferencesCardProps) {
  return (
    <div className="w-full px-6 mb-8">
      <h2 className="text-xl font-semibold text-white mb-4 pl-1">Style Preferences</h2>
      
      <div className="bg-black/10 backdrop-blur-md border border-white/10 rounded-[24px] p-6 w-full">
        {/* Favorite Styles */}
        <div className="mb-6">
          <h3 className="text-sm text-white mb-3">Favorite Styles</h3>
          <div className="flex flex-wrap gap-2">
            {favoriteStyles.map((style) => (
              <div 
                key={style}
                className="px-4 py-2 bg-[#3E3E3E] rounded-full"
              >
                <span className="text-sm text-white">{style}</span>
              </div>
            ))}
          </div>
        </div>

        {/* Color Preferences */}
        <div className="mb-6">
          <h3 className="text-sm text-white mb-3">Color Preferences</h3>
          <div className="flex flex-wrap gap-2">
            {colorPreferences.map((color) => (
              <div 
                key={color}
                className="px-4 py-2 bg-[#3E3E3E] rounded-full"
              >
                <span className="text-sm text-white">{color}</span>
              </div>
            ))}
          </div>
        </div>

        {/* Edit Preferences Button */}
        <button className="w-full h-[48px] bg-white/5 hover:bg-white/10 rounded-[12px] flex items-center justify-center gap-1 transition-colors group">
          <span className="text-[15px] font-medium text-white">Edit Preferences</span>
          <ChevronRight className="w-4 h-4 text-white/70 group-hover:translate-x-0.5 transition-transform" />
        </button>
      </div>
    </div>
  );
}
