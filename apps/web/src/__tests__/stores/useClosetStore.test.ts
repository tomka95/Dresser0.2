import { describe, it, expect, beforeEach, vi } from 'vitest';
import { useClosetStore } from '@/stores/useClosetStore';
import type { ClosetItem } from '@dresser/contracts';
import * as api from '@/lib/api/closet';

// Mock the API layer
vi.mock('@/lib/api/closet', () => ({
  listClosetItems: vi.fn(),
  addClosetItem: vi.fn(),
}));

describe('useClosetStore', () => {
  beforeEach(() => {
    // Reset store state before each test
    useClosetStore.setState({
      items: [],
      isLoading: false,
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
    it('should add item successfully', async () => {
      const newItem: ClosetItem = {
        id: '2',
        userId: 'user-1',
        name: 'New Item',
        category: 'bottom',
        createdAt: '2024-01-02T00:00:00Z',
        updatedAt: '2024-01-02T00:00:00Z',
      };

      vi.mocked(api.addClosetItem).mockResolvedValue(newItem);

      const store = useClosetStore.getState();
      await store.addItem({
        name: 'New Item',
        category: 'bottom',
      });

      expect(useClosetStore.getState().items).toContainEqual(newItem);
      expect(useClosetStore.getState().isLoading).toBe(false);
      expect(useClosetStore.getState().error).toBeUndefined();
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

    it('should append to existing items', async () => {
      const existingItem: ClosetItem = {
        id: '1',
        userId: 'user-1',
        name: 'Existing',
        category: 'top',
        createdAt: '2024-01-01T00:00:00Z',
        updatedAt: '2024-01-01T00:00:00Z',
      };

      useClosetStore.setState({ items: [existingItem] });

      const newItem: ClosetItem = {
        id: '2',
        userId: 'user-1',
        name: 'New',
        category: 'bottom',
        createdAt: '2024-01-02T00:00:00Z',
        updatedAt: '2024-01-02T00:00:00Z',
      };

      vi.mocked(api.addClosetItem).mockResolvedValue(newItem);

      const store = useClosetStore.getState();
      await store.addItem({
        name: 'New',
        category: 'bottom',
      });

      const state = useClosetStore.getState();
      expect(state.items).toHaveLength(2);
      expect(state.items).toContainEqual(existingItem);
      expect(state.items).toContainEqual(newItem);
    });
  });
});






