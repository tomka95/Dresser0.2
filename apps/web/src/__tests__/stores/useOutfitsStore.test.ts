import { describe, it, expect, beforeEach, vi } from 'vitest';
import { useOutfitsStore } from '@/stores/useOutfitsStore';
import type { OutfitSuggestion } from '@tailor/contracts';
import * as api from '@/lib/api/outfits';

// Mock the API layer
vi.mock('@/lib/api/outfits', () => ({
  suggestOutfits: vi.fn(),
}));

describe('useOutfitsStore', () => {
  beforeEach(() => {
    // Reset store state before each test
    useOutfitsStore.setState({
      outfits: [],
      likedOutfits: [],
      isLoading: false,
      error: undefined,
    });
    vi.clearAllMocks();
  });

  describe('fetchOutfits', () => {
    it('should load outfits successfully', async () => {
      const mockOutfits: OutfitSuggestion[] = [
        {
          id: 'outfit-1',
          userId: 'user-1',
          name: 'Casual Look',
          items: ['item-1', 'item-2'],
          createdAt: '2024-01-01T00:00:00Z',
        },
      ];

      vi.mocked(api.suggestOutfits).mockResolvedValue(mockOutfits);

      const store = useOutfitsStore.getState();
      await store.fetchOutfits({ limit: 3 });

      expect(useOutfitsStore.getState().outfits).toEqual(mockOutfits);
      expect(useOutfitsStore.getState().isLoading).toBe(false);
      expect(useOutfitsStore.getState().error).toBeUndefined();
    });

    it('should pass options to API', async () => {
      vi.mocked(api.suggestOutfits).mockResolvedValue([]);

      const store = useOutfitsStore.getState();
      await store.fetchOutfits({ limit: 5 });

      expect(api.suggestOutfits).toHaveBeenCalledWith({ limit: 5 });
    });

    it('should handle errors', async () => {
      const errorMessage = 'Failed to fetch outfits';
      vi.mocked(api.suggestOutfits).mockRejectedValue(
        new Error(errorMessage)
      );

      const store = useOutfitsStore.getState();
      await store.fetchOutfits();

      expect(useOutfitsStore.getState().outfits).toEqual([]);
      expect(useOutfitsStore.getState().isLoading).toBe(false);
      expect(useOutfitsStore.getState().error).toBe(errorMessage);
    });

    it('should not fetch if already loading', async () => {
      useOutfitsStore.setState({ isLoading: true });
      const store = useOutfitsStore.getState();
      await store.fetchOutfits();

      expect(api.suggestOutfits).not.toHaveBeenCalled();
    });
  });

  describe('toggleLike', () => {
    it('should add outfit to liked list', () => {
      const store = useOutfitsStore.getState();
      store.toggleLike('outfit-1');

      expect(useOutfitsStore.getState().likedOutfits).toContain('outfit-1');
    });

    it('should remove outfit from liked list if already liked', () => {
      useOutfitsStore.setState({ likedOutfits: ['outfit-1'] });

      const store = useOutfitsStore.getState();
      store.toggleLike('outfit-1');

      expect(useOutfitsStore.getState().likedOutfits).not.toContain('outfit-1');
    });

    it('should handle multiple likes', () => {
      const store = useOutfitsStore.getState();
      store.toggleLike('outfit-1');
      store.toggleLike('outfit-2');

      const liked = useOutfitsStore.getState().likedOutfits;
      expect(liked).toContain('outfit-1');
      expect(liked).toContain('outfit-2');
      expect(liked).toHaveLength(2);
    });
  });
});






