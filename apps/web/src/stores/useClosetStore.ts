import { create } from 'zustand';

import type { ClosetItem } from '@dresser/contracts';

import {
  addClosetItem as apiAddClosetItem,
  listClosetItems as apiListClosetItems,
} from '@/lib/api/closet';

type NewClosetItemInput = Omit<
  ClosetItem,
  'id' | 'userId' | 'createdAt' | 'updatedAt'
>;

type ClosetState = {
  items: ClosetItem[];
  isLoading: boolean;
  error?: string;
  fetchItems: () => Promise<void>;
  addItem: (input: NewClosetItemInput) => Promise<void>;
};

export const useClosetStore = create<ClosetState>((set, get) => ({
  items: [],
  isLoading: false,
  error: undefined,
  async fetchItems() {
    // Avoid duplicate work if already loading
    if (get().isLoading) {
      return;
    }

    set({ isLoading: true, error: undefined });

    try {
      const items = await apiListClosetItems();
      set({ items, isLoading: false });
    } catch (error) {
      set({
        isLoading: false,
        error:
          error instanceof Error
            ? error.message
            : 'Failed to load closet items',
      });
    }
  },
  async addItem(input) {
    set({ isLoading: true, error: undefined });

    try {
      const newItem = await apiAddClosetItem(input);
      set((state) => ({
        items: [...state.items, newItem],
        isLoading: false,
      }));
    } catch (error) {
      set({
        isLoading: false,
        error:
          error instanceof Error
            ? error.message
            : 'Failed to add closet item',
      });
    }
  },
}));






