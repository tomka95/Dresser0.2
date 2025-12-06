import { create } from 'zustand';

import type { OutfitSuggestion } from '@dresser/contracts';

import { suggestOutfits as apiSuggestOutfits } from '@/lib/api/outfits';

type FetchOptions = {
  limit?: number;
};

type OutfitsState = {
  outfits: OutfitSuggestion[];
  likedOutfits: string[];
  isLoading: boolean;
  error?: string;
  fetchOutfits: (options?: FetchOptions) => Promise<void>;
  toggleLike: (outfitId: string) => void;
};

export const useOutfitsStore = create<OutfitsState>((set, get) => ({
  outfits: [],
  likedOutfits: [],
  isLoading: false,
  error: undefined,
  async fetchOutfits(options) {
    if (get().isLoading) {
      return;
    }

    set({ isLoading: true, error: undefined });

    try {
      const outfits = await apiSuggestOutfits(options);
      set({ outfits, isLoading: false });
    } catch (error) {
      set({
        isLoading: false,
        error:
          error instanceof Error
            ? error.message
            : 'Failed to load outfit suggestions',
      });
    }
  },
  toggleLike(outfitId) {
    set((state) => {
      const liked = state.likedOutfits.includes(outfitId);
      return {
        likedOutfits: liked
          ? state.likedOutfits.filter((id) => id !== outfitId)
          : [...state.likedOutfits, outfitId],
      };
    });
  },
}));






