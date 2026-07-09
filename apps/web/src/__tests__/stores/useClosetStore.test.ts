import { describe, it, expect, beforeEach, vi } from 'vitest';
import { useClosetStore } from '@/stores/useClosetStore';
import type { ClosetItem } from '@tailor/contracts';
import * as api from '@/lib/api/closet';

// Mock the API layer
vi.mock('@/lib/api/closet', () => ({
  listClosetItems: vi.fn(),
  addClosetItem: vi.fn(),
  getClosetItem: vi.fn(),
  patchClosetItem: vi.fn(),
}));

describe('useClosetStore', () => {
  beforeEach(() => {
    // Reset store state before each test
    useClosetStore.setState({
      items: [],
      isLoading: false,
      isItemLoading: {},
      hydratedItemIds: {},
      hasFetchedItems: false,
      error: undefined,
    });
    vi.clearAllMocks();
  });

  describe('fetchItems', () => {
    it('should load items successfully', async () => {
      const mockItems: ClosetItem[] = [
        {
          id: '1',
          userId: 'user-1',
          name: 'Test Shirt',
          category: 'top',
          createdAt: '2024-01-01T00:00:00Z',
          updatedAt: '2024-01-01T00:00:00Z',
        },
      ];

      vi.mocked(api.listClosetItems).mockResolvedValue(mockItems);

      const store = useClosetStore.getState();
      await store.fetchItems();

      expect(useClosetStore.getState().items).toEqual(mockItems);
      expect(useClosetStore.getState().isLoading).toBe(false);
      expect(useClosetStore.getState().error).toBeUndefined();
    });

    it('should handle errors', async () => {
      const errorMessage = 'Network error';
      vi.mocked(api.listClosetItems).mockRejectedValue(
        new Error(errorMessage)
      );

      const store = useClosetStore.getState();
      await store.fetchItems();

      expect(useClosetStore.getState().items).toEqual([]);
      expect(useClosetStore.getState().isLoading).toBe(false);
      expect(useClosetStore.getState().error).toBe(errorMessage);
    });

    it('should not fetch if already loading', async () => {
      useClosetStore.setState({ isLoading: true });
      const store = useClosetStore.getState();
      await store.fetchItems();

      expect(api.listClosetItems).not.toHaveBeenCalled();
    });

    it('should set loading state during fetch', async () => {
      let resolvePromise: (value: ClosetItem[]) => void;
      const promise = new Promise<ClosetItem[]>((resolve) => {
        resolvePromise = resolve;
      });

      vi.mocked(api.listClosetItems).mockReturnValue(promise);

      const store = useClosetStore.getState();
      const fetchPromise = store.fetchItems();

      // Check loading state is set
      expect(useClosetStore.getState().isLoading).toBe(true);

      resolvePromise!([]);
      await fetchPromise;

      expect(useClosetStore.getState().isLoading).toBe(false);
    });
  });

  describe('addItem', () => {
    // Photo-seam Phase 4: manual add is asynchronous — the server stages a candidate,
    // tailors the product card through the shared seam, and the item is born via the
    // confirm chokepoint. The store gets a 202 'tailoring' ack (no item to append)
    // and invalidates the cache so the next closet read picks up the newborn.
    const tailoring = {
      status: 'tailoring' as const,
      syncId: 'run-1',
      candidateId: 'cand-1',
      message: 'Tailoring your item — it will appear in your closet shortly.',
    };

    it('should accept the tailoring ack and invalidate the cache', async () => {
      vi.mocked(api.addClosetItem).mockResolvedValue(tailoring);
      useClosetStore.setState({ hasFetchedItems: true });

      const store = useClosetStore.getState();
      await store.addItem({
        name: 'New Item',
        category: 'bottom',
      });

      const state = useClosetStore.getState();
      expect(state.items).toEqual([]);            // nothing appended — not born yet
      expect(state.hasFetchedItems).toBe(false);  // cache dropped for the next read
      expect(state.isLoading).toBe(false);
      expect(state.error).toBeUndefined();
    });

    it('should handle errors when adding item', async () => {
      const errorMessage = 'Failed to add item';
      vi.mocked(api.addClosetItem).mockRejectedValue(new Error(errorMessage));

      const store = useClosetStore.getState();
      await store.addItem({
        name: 'New Item',
        category: 'top',
      });

      expect(useClosetStore.getState().items).toEqual([]);
      expect(useClosetStore.getState().isLoading).toBe(false);
      expect(useClosetStore.getState().error).toBe(errorMessage);
    });

    it('should keep existing items untouched while tailoring', async () => {
      const existingItem: ClosetItem = {
        id: '1',
        userId: 'user-1',
        name: 'Existing',
        category: 'top',
        createdAt: '2024-01-01T00:00:00Z',
        updatedAt: '2024-01-01T00:00:00Z',
      };

      useClosetStore.setState({ items: [existingItem] });
      vi.mocked(api.addClosetItem).mockResolvedValue(tailoring);

      const store = useClosetStore.getState();
      await store.addItem({
        name: 'New',
        category: 'bottom',
      });

      const state = useClosetStore.getState();
      expect(state.items).toEqual([existingItem]);  // untouched until the item is born
      expect(state.hasFetchedItems).toBe(false);
    });
  });

  describe('fetchItem', () => {
    it('should return cached item when present and hydrated', async () => {
      const cachedItem: ClosetItem = {
        id: '1',
        userId: 'user-1',
        name: 'Cached Item',
        category: 'top',
        createdAt: '2024-01-01T00:00:00Z',
        updatedAt: '2024-01-01T00:00:00Z',
      };

      useClosetStore.setState({ 
        items: [cachedItem],
        hydratedItemIds: { '1': true },
      });

      const store = useClosetStore.getState();
      const result = await store.fetchItem('1');

      expect(result).toEqual(cachedItem);
      expect(api.getClosetItem).not.toHaveBeenCalled();
      expect(useClosetStore.getState().items).toHaveLength(1);
    });

    it('should call API and upsert when item is missing', async () => {
      const fetchedItem: ClosetItem = {
        id: '2',
        userId: 'user-1',
        name: 'Fetched Item',
        category: 'bottom',
        createdAt: '2024-01-02T00:00:00Z',
        updatedAt: '2024-01-02T00:00:00Z',
      };

      vi.mocked(api.getClosetItem).mockResolvedValue(fetchedItem);

      const store = useClosetStore.getState();
      const result = await store.fetchItem('2');

      expect(result).toEqual(fetchedItem);
      expect(api.getClosetItem).toHaveBeenCalledWith('2');
      expect(useClosetStore.getState().items).toContainEqual(fetchedItem);
      expect(useClosetStore.getState().isItemLoading['2']).toBe(false);
      expect(useClosetStore.getState().hydratedItemIds['2']).toBe(true);
    });

    it('should call API when item exists but not hydrated', async () => {
      const itemNotHydrated: ClosetItem = {
        id: '3',
        userId: 'user-1',
        name: 'Item Not Hydrated',
        category: 'top',
        createdAt: '2024-01-01T00:00:00Z',
        updatedAt: '2024-01-01T00:00:00Z',
      };

      const fetchedItem: ClosetItem = {
        id: '3',
        userId: 'user-1',
        name: 'Item Not Hydrated',
        category: 'top',
        createdAt: '2024-01-01T00:00:00Z',
        updatedAt: '2024-01-02T00:00:00Z',
      };

      useClosetStore.setState({ items: [itemNotHydrated] });
      vi.mocked(api.getClosetItem).mockResolvedValue(fetchedItem);

      const store = useClosetStore.getState();
      const result = await store.fetchItem('3');

      expect(result).toEqual(fetchedItem);
      expect(api.getClosetItem).toHaveBeenCalledWith('3');
      expect(useClosetStore.getState().items).toHaveLength(1);
      expect(useClosetStore.getState().hydratedItemIds['3']).toBe(true);
    });

    it('should mark item as hydrated after successful fetch', async () => {
      const fetchedItem: ClosetItem = {
        id: '6',
        userId: 'user-1',
        name: 'New Item',
        category: 'bottom',
        createdAt: '2024-01-02T00:00:00Z',
        updatedAt: '2024-01-02T00:00:00Z',
      };

      vi.mocked(api.getClosetItem).mockResolvedValue(fetchedItem);

      const store = useClosetStore.getState();
      await store.fetchItem('6');

      expect(useClosetStore.getState().hydratedItemIds['6']).toBe(true);
    });

    it('should not refetch item if already hydrated', async () => {
      const hydratedItem: ClosetItem = {
        id: '5',
        userId: 'user-1',
        name: 'Hydrated Item',
        category: 'top',
        createdAt: '2024-01-01T00:00:00Z',
        updatedAt: '2024-01-01T00:00:00Z',
      };

      // Set item in store and mark as hydrated
      useClosetStore.setState({ 
        items: [hydratedItem],
        hydratedItemIds: { '5': true },
      });

      const store = useClosetStore.getState();
      const result = await store.fetchItem('5');

      // Should return cached item without API call
      expect(result).toEqual(hydratedItem);
      expect(api.getClosetItem).not.toHaveBeenCalled();
      expect(useClosetStore.getState().items).toHaveLength(1);
    });

    it('should handle 404 error', async () => {
      const errorMessage = 'Closet item not found: 999';
      vi.mocked(api.getClosetItem).mockRejectedValue(new Error(errorMessage));

      const store = useClosetStore.getState();
      
      await expect(store.fetchItem('999')).rejects.toThrow(errorMessage);
      
      expect(useClosetStore.getState().error).toBe(errorMessage);
      expect(useClosetStore.getState().isItemLoading['999']).toBe(false);
      expect(useClosetStore.getState().items).toEqual([]);
    });

  });

  describe('updateItem', () => {
    it('should patch and update store', async () => {
      const existingItem: ClosetItem = {
        id: '1',
        userId: 'user-1',
        name: 'Original Name',
        category: 'top',
        createdAt: '2024-01-01T00:00:00Z',
        updatedAt: '2024-01-01T00:00:00Z',
      };

      const updatedItem: ClosetItem = {
        id: '1',
        userId: 'user-1',
        name: 'Updated Name',
        category: 'top',
        createdAt: '2024-01-01T00:00:00Z',
        updatedAt: '2024-01-02T00:00:00Z',
      };

      useClosetStore.setState({ items: [existingItem] });
      vi.mocked(api.patchClosetItem).mockResolvedValue(updatedItem);

      const store = useClosetStore.getState();
      const result = await store.updateItem('1', {
        name: 'Updated Name',
      });

      expect(result).toEqual(updatedItem);
      expect(api.patchClosetItem).toHaveBeenCalledWith('1', {
        name: 'Updated Name',
      });
      expect(useClosetStore.getState().items).toHaveLength(1);
      expect(useClosetStore.getState().items[0]).toEqual(updatedItem);
      expect(useClosetStore.getState().isItemLoading['1']).toBe(false);
      expect(useClosetStore.getState().hydratedItemIds['1']).toBe(true);
    });

    it('should add item to store if not present', async () => {
      const updatedItem: ClosetItem = {
        id: '2',
        userId: 'user-1',
        name: 'New Item',
        category: 'bottom',
        createdAt: '2024-01-01T00:00:00Z',
        updatedAt: '2024-01-02T00:00:00Z',
      };

      vi.mocked(api.patchClosetItem).mockResolvedValue(updatedItem);

      const store = useClosetStore.getState();
      await store.updateItem('2', { name: 'New Item' });

      expect(useClosetStore.getState().items).toContainEqual(updatedItem);
      expect(useClosetStore.getState().hydratedItemIds['2']).toBe(true);
    });

    it('should bubble up validation error and not mutate store on failure', async () => {
      const existingItem: ClosetItem = {
        id: '1',
        userId: 'user-1',
        name: 'Original Name',
        category: 'top',
        createdAt: '2024-01-01T00:00:00Z',
        updatedAt: '2024-01-01T00:00:00Z',
      };

      useClosetStore.setState({ items: [existingItem] });
      
      const validationError = new Error('Item name cannot be empty');
      vi.mocked(api.patchClosetItem).mockRejectedValue(validationError);

      const store = useClosetStore.getState();
      
      await expect(
        store.updateItem('1', { name: '' })
      ).rejects.toThrow('Item name cannot be empty');

      // Store should not be mutated
      expect(useClosetStore.getState().items).toHaveLength(1);
      expect(useClosetStore.getState().items[0]).toEqual(existingItem);
      expect(useClosetStore.getState().error).toBe('Item name cannot be empty');
      expect(useClosetStore.getState().isItemLoading['1']).toBe(false);
    });

  });
});






