import { create } from 'zustand';

import type { OutfitSuggestion } from '@tailor/contracts';

import {
  generateOutfit as apiGenerateOutfit,
  listOutfits as apiListOutfits,
  setOutfitLiked as apiSetOutfitLiked,
  unsaveOutfit as apiUnsaveOutfit,
} from '@/lib/api/outfits';

type OutfitsState = {
  outfits: OutfitSuggestion[];
  /** Derived from the server's isLiked — kept as an id list for cheap lookups. */
  likedOutfits: string[];
  isLoading: boolean;
  isGenerating: boolean;
  error?: string;
  /** Honest composer gap message from the last generate (closet can't complete
   * a look). Cleared on the next successful generate/fetch. */
  generateNotice?: string;
  fetchOutfits: () => Promise<void>;
  /** Compose a new look server-side. Returns true when a look was added. */
  generateOutfit: (occasion?: string) => Promise<boolean>;
  toggleLike: (outfitId: string) => Promise<void>;
  unsave: (outfitId: string) => Promise<void>;
};

const likedIds = (outfits: OutfitSuggestion[]) =>
  outfits.filter((o) => o.isLiked).map((o) => o.id);

export const useOutfitsStore = create<OutfitsState>((set, get) => ({
  outfits: [],
  likedOutfits: [],
  isLoading: false,
  isGenerating: false,
  error: undefined,
  generateNotice: undefined,

  async fetchOutfits() {
    if (get().isLoading) {
      return;
    }

    set({ isLoading: true, error: undefined });

    try {
      const outfits = await apiListOutfits();
      set({ outfits, likedOutfits: likedIds(outfits), isLoading: false });
    } catch (error) {
      set({
        isLoading: false,
        error:
          error instanceof Error ? error.message : 'Failed to load your outfits',
      });
    }
  },

  async generateOutfit(occasion) {
    if (get().isGenerating) {
      return false;
    }

    set({ isGenerating: true, error: undefined, generateNotice: undefined });

    // Variety steering: exclude what's already on screen so the composer
    // reaches for different pieces (the server dedups identical sets anyway).
    const excludeItemIds = get()
      .outfits.flatMap((o) => o.items)
      .slice(0, 30);

    try {
      const result = await apiGenerateOutfit({ occasion, excludeItemIds });
      if (!result.sufficient || !result.outfit) {
        // The closet honestly can't complete a look — surface the gap.
        set({
          isGenerating: false,
          generateNotice:
            result.note ||
            (result.gaps.length
              ? `Your closet is missing a ${result.gaps.join(' and a ')} for this.`
              : 'Tailor could not build a full look from your closet yet.'),
        });
        return false;
      }
      const outfit = result.outfit;
      set((state) => {
        const rest = state.outfits.filter((o) => o.id !== outfit.id);
        const outfits = [outfit, ...rest];
        return { outfits, likedOutfits: likedIds(outfits), isGenerating: false };
      });
      return true;
    } catch (error) {
      set({
        isGenerating: false,
        error:
          error instanceof Error ? error.message : 'Failed to generate an outfit',
      });
      return false;
    }
  },

  async toggleLike(outfitId) {
    const current = get().outfits.find((o) => o.id === outfitId);
    if (!current) return;
    const liked = !current.isLiked;

    // Optimistic flip; revert if the server rejects it.
    const apply = (value: boolean) =>
      set((state) => {
        const outfits = state.outfits.map((o) =>
          o.id === outfitId ? { ...o, isLiked: value } : o
        );
        return { outfits, likedOutfits: likedIds(outfits) };
      });

    apply(liked);
    try {
      await apiSetOutfitLiked(outfitId, liked);
    } catch {
      apply(!liked);
    }
  },

  async unsave(outfitId) {
    const previous = get().outfits;
    const outfits = previous.filter((o) => o.id !== outfitId);
    set({ outfits, likedOutfits: likedIds(outfits) });
    try {
      await apiUnsaveOutfit(outfitId);
    } catch {
      set({ outfits: previous, likedOutfits: likedIds(previous) });
    }
  },
}));
