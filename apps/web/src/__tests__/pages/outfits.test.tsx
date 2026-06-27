import { describe, it, expect, beforeEach, vi, type Mock } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import OutfitsPage from '@/app/outfits/page';
import { useOutfitsStore } from '@/stores/useOutfitsStore';
import { useClosetStore } from '@/stores/useClosetStore';
import type { OutfitSuggestion } from '@tailor/contracts';
import type { ClosetItem } from '@tailor/contracts';

// The OutfitsPage only reads items/isLoading/fetchItems from the closet store, so
// we mock just that slice (cast to Mock so the partial selector input is allowed,
// mirroring closet.test.tsx) rather than constructing the full ClosetState.
type ClosetStoreSlice = {
  items: ClosetItem[];
  isLoading: boolean;
  fetchItems: () => void;
};

// Mock the stores
vi.mock('@/stores/useOutfitsStore', () => ({
  useOutfitsStore: vi.fn(),
}));

vi.mock('@/stores/useClosetStore', () => ({
  useClosetStore: vi.fn(),
}));

// Mock analytics
vi.mock('@/lib/analytics', () => ({
  track: vi.fn(),
}));

describe('OutfitsPage', () => {
  const mockFetchOutfits = vi.fn();
  const mockToggleLike = vi.fn();
  const mockFetchClosetItems = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(useOutfitsStore).mockImplementation((selector) => {
      const state = {
        outfits: [] as OutfitSuggestion[],
        likedOutfits: [] as string[],
        isLoading: false,
        error: undefined as string | undefined,
        fetchOutfits: mockFetchOutfits,
        toggleLike: mockToggleLike,
      };
      return selector(state);
    });
    (useClosetStore as unknown as Mock).mockImplementation(
      (selector: (s: ClosetStoreSlice) => unknown) =>
        selector({ items: [], isLoading: false, fetchItems: mockFetchClosetItems })
    );
  });

  it('should render empty state when no outfits', () => {
    render(<OutfitsPage />);

    expect(screen.getByText('No outfit suggestions yet')).toBeInTheDocument();
  });

  it('should render loading state', () => {
    vi.mocked(useOutfitsStore).mockImplementation((selector) => {
      const state = {
        outfits: [],
        likedOutfits: [],
        isLoading: true,
        error: undefined,
        fetchOutfits: mockFetchOutfits,
        toggleLike: mockToggleLike,
      };
      return selector(state);
    });

    render(<OutfitsPage />);

    expect(
      screen.getByText('Generating personalized looks…')
    ).toBeInTheDocument();
  });

  it('should render error state', () => {
    vi.mocked(useOutfitsStore).mockImplementation((selector) => {
      const state = {
        outfits: [],
        likedOutfits: [],
        isLoading: false,
        error: 'Failed to load',
        fetchOutfits: mockFetchOutfits,
        toggleLike: mockToggleLike,
      };
      return selector(state);
    });

    render(<OutfitsPage />);

    expect(screen.getByText(/Failed to load/)).toBeInTheDocument();
  });

  it('should render outfit suggestions', () => {
    const mockOutfits: OutfitSuggestion[] = [
      {
        id: 'outfit-1',
        userId: 'user-1',
        name: 'Weekend Look',
        occasion: 'Casual',
        items: ['item-1'],
        createdAt: '2024-01-01T00:00:00Z',
      },
    ];

    const mockClosetItems: ClosetItem[] = [
      {
        id: 'item-1',
        userId: 'user-1',
        name: 'Blue Shirt',
        category: 'top',
        createdAt: '2024-01-01T00:00:00Z',
        updatedAt: '2024-01-01T00:00:00Z',
      },
    ];

    vi.mocked(useOutfitsStore).mockImplementation((selector) => {
      const state = {
        outfits: mockOutfits,
        likedOutfits: [],
        isLoading: false,
        error: undefined,
        fetchOutfits: mockFetchOutfits,
        toggleLike: mockToggleLike,
      };
      return selector(state);
    });

    (useClosetStore as unknown as Mock).mockImplementation(
      (selector: (s: ClosetStoreSlice) => unknown) =>
        selector({ items: mockClosetItems, isLoading: false, fetchItems: mockFetchClosetItems })
    );

    render(<OutfitsPage />);

    expect(screen.getByText('Weekend Look')).toBeInTheDocument();
    expect(screen.getByText('Occasion: Casual')).toBeInTheDocument();
    expect(screen.getByText('Blue Shirt')).toBeInTheDocument();
  });

  it('should call fetchOutfits on mount when outfits are empty', () => {
    render(<OutfitsPage />);

    expect(mockFetchOutfits).toHaveBeenCalledWith({ limit: 3 });
  });

  it('should handle like button click', async () => {
    const mockOutfits: OutfitSuggestion[] = [
      {
        id: 'outfit-1',
        userId: 'user-1',
        name: 'Test Outfit',
        items: [],
        createdAt: '2024-01-01T00:00:00Z',
      },
    ];

    vi.mocked(useOutfitsStore).mockImplementation((selector) => {
      const state = {
        outfits: mockOutfits,
        likedOutfits: [],
        isLoading: false,
        error: undefined,
        fetchOutfits: mockFetchOutfits,
        toggleLike: mockToggleLike,
      };
      return selector(state);
    });

    render(<OutfitsPage />);

    const likeButton = screen.getByText('☆ Like');
    const user = userEvent.setup();
    await user.click(likeButton);

    expect(mockToggleLike).toHaveBeenCalledWith('outfit-1');
  });

  it('should show liked state when outfit is liked', () => {
    const mockOutfits: OutfitSuggestion[] = [
      {
        id: 'outfit-1',
        userId: 'user-1',
        name: 'Test Outfit',
        items: [],
        createdAt: '2024-01-01T00:00:00Z',
      },
    ];

    vi.mocked(useOutfitsStore).mockImplementation((selector) => {
      const state = {
        outfits: mockOutfits,
        likedOutfits: ['outfit-1'],
        isLoading: false,
        error: undefined,
        fetchOutfits: mockFetchOutfits,
        toggleLike: mockToggleLike,
      };
      return selector(state);
    });

    render(<OutfitsPage />);

    expect(screen.getByText('★ Liked')).toBeInTheDocument();
  });

  it('should handle regenerate button click', async () => {
    const user = userEvent.setup();

    render(<OutfitsPage />);

    const regenerateButton = screen.getByText('Generate Outfit');
    await user.click(regenerateButton);

    expect(mockFetchOutfits).toHaveBeenCalledWith({ limit: 3 });
  });

  it('should render recommended items when present', () => {
    const mockOutfits: OutfitSuggestion[] = [
      {
        id: 'outfit-1',
        userId: 'user-1',
        name: 'Test Outfit',
        items: [],
        recommendedItems: [
          { id: 'rec-1', name: 'Recommended Shoe', reason: 'Completes the look' },
        ],
        createdAt: '2024-01-01T00:00:00Z',
      },
    ];

    vi.mocked(useOutfitsStore).mockImplementation((selector) => {
      const state = {
        outfits: mockOutfits,
        likedOutfits: [],
        isLoading: false,
        error: undefined,
        fetchOutfits: mockFetchOutfits,
        toggleLike: mockToggleLike,
      };
      return selector(state);
    });

    render(<OutfitsPage />);

    expect(screen.getByText('Recommended additions')).toBeInTheDocument();
    expect(screen.getByText('Recommended Shoe')).toBeInTheDocument();
    // The reason renders inside a <span> as "– {reason}" (prefix + text node),
    // so the text is split. Match with a regex rather than an exact string.
    expect(screen.getByText(/Completes the look/)).toBeInTheDocument();
  });
});






