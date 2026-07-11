import { describe, it, expect, beforeEach, vi } from 'vitest';
import { useOutfitsStore } from '@/stores/useOutfitsStore';
import type { OutfitSuggestion } from '@tailor/contracts';
import * as api from '@/lib/api/outfits';

// Mock the real API layer (GET /outfits, POST /outfits/generate, like, unsave).
vi.mock('@/lib/api/outfits', () => ({
  listOutfits: vi.fn(),
  generateOutfit: vi.fn(),
  setOutfitLiked: vi.fn(),
  unsaveOutfit: vi.fn(),
}));

function outfitFixture(overrides: Partial<OutfitSuggestion> = {}): OutfitSuggestion {
  return {
    id: 'outfit-1',
    userId: 'user-1',
    name: 'Casual Look',
    occasion: 'Casual',
    items: ['item-1', 'item-2'],
    rationale: null,
    source: 'composer',
    status: 'active',
    isLiked: false,
    createdAt: '2024-01-01T00:00:00.000Z',
    ...overrides,
  };
}

describe('useOutfitsStore', () => {
  beforeEach(() => {
    // Reset store state before each test
    useOutfitsStore.setState({
      outfits: [],
      likedOutfits: [],
      isLoading: false,
      isGenerating: false,
      error: undefined,
      generateNotice: undefined,
    });
    vi.clearAllMocks();
  });

  describe('fetchOutfits', () => {
    it('should load outfits and derive liked ids from the server state', async () => {
      const mockOutfits = [
        outfitFixture(),
        outfitFixture({ id: 'outfit-2', isLiked: true }),
      ];

      vi.mocked(api.listOutfits).mockResolvedValue(mockOutfits);

      await useOutfitsStore.getState().fetchOutfits();

      expect(useOutfitsStore.getState().outfits).toEqual(mockOutfits);
      expect(useOutfitsStore.getState().likedOutfits).toEqual(['outfit-2']);
      expect(useOutfitsStore.getState().isLoading).toBe(false);
      expect(useOutfitsStore.getState().error).toBeUndefined();
    });

    it('should handle errors', async () => {
      const errorMessage = 'Failed to fetch outfits';
      vi.mocked(api.listOutfits).mockRejectedValue(new Error(errorMessage));

      await useOutfitsStore.getState().fetchOutfits();

      expect(useOutfitsStore.getState().outfits).toEqual([]);
      expect(useOutfitsStore.getState().isLoading).toBe(false);
      expect(useOutfitsStore.getState().error).toBe(errorMessage);
    });

    it('should not fetch if already loading', async () => {
      useOutfitsStore.setState({ isLoading: true });
      await useOutfitsStore.getState().fetchOutfits();

      expect(api.listOutfits).not.toHaveBeenCalled();
    });
  });

  describe('generateOutfit', () => {
    it('should prepend the generated outfit on success', async () => {
      useOutfitsStore.setState({ outfits: [outfitFixture({ id: 'existing' })] });
      const generated = outfitFixture({ id: 'outfit-new' });
      vi.mocked(api.generateOutfit).mockResolvedValue({
        saved: true,
        sufficient: true,
        gaps: [],
        outfit: generated,
      });

      const added = await useOutfitsStore.getState().generateOutfit();

      expect(added).toBe(true);
      expect(useOutfitsStore.getState().outfits[0]).toEqual(generated);
      expect(useOutfitsStore.getState().outfits).toHaveLength(2);
      // Variety steering: the on-screen item ids were sent as exclusions.
      expect(api.generateOutfit).toHaveBeenCalledWith({
        occasion: undefined,
        excludeItemIds: ['item-1', 'item-2'],
      });
    });

    it('should surface the honest gap notice and add nothing when insufficient', async () => {
      vi.mocked(api.generateOutfit).mockResolvedValue({
        saved: false,
        sufficient: false,
        gaps: ['footwear'],
        note: null,
        outfit: null,
      });

      const added = await useOutfitsStore.getState().generateOutfit();

      expect(added).toBe(false);
      expect(useOutfitsStore.getState().outfits).toEqual([]);
      expect(useOutfitsStore.getState().generateNotice).toMatch(/footwear/);
    });

    it('should not stack a duplicate when the server dedups (idempotent)', async () => {
      const existing = outfitFixture({ id: 'outfit-1' });
      useOutfitsStore.setState({ outfits: [existing] });
      vi.mocked(api.generateOutfit).mockResolvedValue({
        saved: true,
        sufficient: true,
        gaps: [],
        outfit: existing,
        idempotent: true,
      });

      await useOutfitsStore.getState().generateOutfit();

      expect(useOutfitsStore.getState().outfits).toHaveLength(1);
    });

    it('should record errors', async () => {
      vi.mocked(api.generateOutfit).mockRejectedValue(new Error('boom'));

      const added = await useOutfitsStore.getState().generateOutfit();

      expect(added).toBe(false);
      expect(useOutfitsStore.getState().error).toBe('boom');
    });
  });

  describe('toggleLike', () => {
    it('should optimistically like and persist via the API', async () => {
      useOutfitsStore.setState({ outfits: [outfitFixture()] });
      vi.mocked(api.setOutfitLiked).mockResolvedValue({
        ok: true,
        outfitId: 'outfit-1',
        liked: true,
      });

      await useOutfitsStore.getState().toggleLike('outfit-1');

      expect(api.setOutfitLiked).toHaveBeenCalledWith('outfit-1', true);
      expect(useOutfitsStore.getState().likedOutfits).toContain('outfit-1');
      expect(useOutfitsStore.getState().outfits[0].isLiked).toBe(true);
    });

    it('should unlike a liked outfit', async () => {
      useOutfitsStore.setState({
        outfits: [outfitFixture({ isLiked: true })],
        likedOutfits: ['outfit-1'],
      });
      vi.mocked(api.setOutfitLiked).mockResolvedValue({
        ok: true,
        outfitId: 'outfit-1',
        liked: false,
      });

      await useOutfitsStore.getState().toggleLike('outfit-1');

      expect(api.setOutfitLiked).toHaveBeenCalledWith('outfit-1', false);
      expect(useOutfitsStore.getState().likedOutfits).not.toContain('outfit-1');
    });

    it('should revert the optimistic flip when the API rejects', async () => {
      useOutfitsStore.setState({ outfits: [outfitFixture()] });
      vi.mocked(api.setOutfitLiked).mockRejectedValue(new Error('nope'));

      await useOutfitsStore.getState().toggleLike('outfit-1');

      expect(useOutfitsStore.getState().likedOutfits).not.toContain('outfit-1');
      expect(useOutfitsStore.getState().outfits[0].isLiked).toBe(false);
    });

    it('should ignore unknown outfit ids', async () => {
      await useOutfitsStore.getState().toggleLike('missing');

      expect(api.setOutfitLiked).not.toHaveBeenCalled();
    });
  });

  describe('unsave', () => {
    it('should remove the outfit and persist via the API', async () => {
      useOutfitsStore.setState({ outfits: [outfitFixture()] });
      vi.mocked(api.unsaveOutfit).mockResolvedValue({ ok: true, outfitId: 'outfit-1' });

      await useOutfitsStore.getState().unsave('outfit-1');

      expect(api.unsaveOutfit).toHaveBeenCalledWith('outfit-1');
      expect(useOutfitsStore.getState().outfits).toEqual([]);
    });

    it('should restore the outfit when the API rejects', async () => {
      const outfit = outfitFixture();
      useOutfitsStore.setState({ outfits: [outfit] });
      vi.mocked(api.unsaveOutfit).mockRejectedValue(new Error('nope'));

      await useOutfitsStore.getState().unsave('outfit-1');

      expect(useOutfitsStore.getState().outfits).toEqual([outfit]);
    });
  });
});
