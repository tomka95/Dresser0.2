import { create } from 'zustand';

import type { ClosetItem, ClosetItemUpdate } from '@tailor/contracts';

import {
  addClosetItem as apiAddClosetItem,
  listClosetItems as apiListClosetItems,
  getClosetItem as apiGetClosetItem,
  patchClosetItem as apiPatchClosetItem,
} from '@/lib/api/closet';

type NewClosetItemInput = Omit<
  ClosetItem,
  'id' | 'userId' | 'createdAt' | 'updatedAt' | 'analysisRaw'
>;

type ClosetState = {
  items: ClosetItem[];
  isLoading: boolean;
  isItemLoading: Record<string, boolean>; // Track per-item loading
  hydratedItemIds: Record<string, boolean>; // Track items that have been fetched from network (prevents refetching items with zero tags)
  error?: string;
  fetchItems: () => Promise<void>;
  addItem: (input: NewClosetItemInput) => Promise<void>;
  fetchItem: (id: string) => Promise<ClosetItem>;
  updateItem: (id: string, updates: ClosetItemUpdate) => Promise<ClosetItem>;
};

export const useClosetStore = create<ClosetState>((set, get) => ({
  items: [],
  isLoading: false,
  isItemLoading: {},
  hydratedItemIds: {},
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
  async fetchItem(id: string) {
    const state = get();
    
    // Check if item exists in store and has been hydrated from network
    const existingItem = state.items.find((item) => item.id === id);
    if (existingItem && state.hydratedItemIds[id]) {
      // Return cached item immediately if it has been hydrated
      return existingItem;
    }

    // Set loading state for this item (don't block if already loading - allow concurrent requests)
    set((state) => ({
      isItemLoading: { ...state.isItemLoading, [id]: true },
      error: undefined,
    }));

    try {
      const item = await apiGetClosetItem(id);

      // Upsert item into items array and mark as hydrated
      set((state) => {
        const existingIndex = state.items.findIndex((i) => i.id === id);
        const updatedItems = [...state.items];
        
        if (existingIndex >= 0) {
          // Update existing item
          updatedItems[existingIndex] = item;
        } else {
          // Add new item
          updatedItems.push(item);
        }

        return {
          items: updatedItems,
          isItemLoading: { ...state.isItemLoading, [id]: false },
          hydratedItemIds: { ...state.hydratedItemIds, [id]: true },
        };
      });

      return item;
    } catch (error) {
      set((state) => ({
        isItemLoading: { ...state.isItemLoading, [id]: false },
        error:
          error instanceof Error
            ? error.message
            : 'Failed to fetch closet item',
      }));
      throw error;
    }
  },
  async updateItem(id: string, updates: ClosetItemUpdate) {
    set((state) => ({
      isItemLoading: { ...state.isItemLoading, [id]: true },
      error: undefined,
    }));

    try {
      const updatedItem = await apiPatchClosetItem(id, updates);

      // Update item in store and mark as hydrated
      set((state) => {
        const existingIndex = state.items.findIndex((item) => item.id === id);
        if (existingIndex >= 0) {
          const updatedItems = [...state.items];
          updatedItems[existingIndex] = updatedItem;
          return {
            items: updatedItems,
            isItemLoading: { ...state.isItemLoading, [id]: false },
            hydratedItemIds: { ...state.hydratedItemIds, [id]: true },
          };
        } else {
          // Item not in store, add it
          return {
            items: [...state.items, updatedItem],
            isItemLoading: { ...state.isItemLoading, [id]: false },
            hydratedItemIds: { ...state.hydratedItemIds, [id]: true },
          };
        }
      });

      return updatedItem;
    } catch (error) {
      set((state) => ({
        isItemLoading: { ...state.isItemLoading, [id]: false },
        error:
          error instanceof Error
            ? error.message
            : 'Failed to update closet item',
      }));
      throw error;
    }
  },
}));







