import { describe, it, expect, beforeEach, vi, type Mock } from 'vitest';
import { render, screen } from '@testing-library/react';
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

// The redesigned page navigates (outfit cards → /outfits/[id]).
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), back: vi.fn() }),
  usePathname: () => '/outfits',
}));

// The redesign added a required useRequireAuth() guard to the /outfits list
// (parity with /outfits/[id]). The component destructures { session, loading }
// and gates on `loading || !session`, so the mock must resolve to an
// authenticated, non-loading session (mirrors review.test.tsx). Without this the
// real hook mounts Supabase auth and every test throws "Supabase is not configured".
vi.mock('@/lib/auth/useRequireAuth', () => ({
  useRequireAuth: () => ({
    session: { user: { id: 'u1' } },
    status: 'authenticated',
    loading: false,
  }),
}));

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

    expect(screen.getByText('No outfits yet')).toBeInTheDocument();
    // Redesigned empty-state CTA copy ("Generate outfits" → "Style me for today").
    expect(screen.getByText('Style me for today')).toBeInTheDocument();
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

    // The redesign replaced the loading COPY with a skeleton list (aria-hidden,
    // no queryable text). The remaining visible loading signal is the header
    // "New look" action entering its pending state — the label is swapped for
    // brand dots (so its accessible name goes empty) and the button is disabled.
    // In the loading branch this is the only button on the page. Assert that real
    // behavior rather than a piece of gone copy.
    const buttons = screen.getAllByRole('button');
    expect(buttons).toHaveLength(1);
    expect(buttons[0]).toBeDisabled();
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
        imageUrl: 'https://example.com/shirt.jpg',
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
    expect(screen.getByText('Casual')).toBeInTheDocument();
    // Item previews render as image thumbnails (alt = item name).
    expect(screen.getByAltText('Blue Shirt')).toBeInTheDocument();
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

    const likeButton = screen.getByRole('button', { name: 'Like outfit' });
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

    expect(screen.getByRole('button', { name: 'Unlike outfit' })).toBeInTheDocument();
  });

  it('should handle regenerate button click', async () => {
    const user = userEvent.setup();

    render(<OutfitsPage />);

    // Redesigned regenerate action is labelled "New look" (was "Regenerate").
    // The BEHAVIOR is unchanged: it must still call fetchOutfits({ limit: 3 }).
    const regenerateButton = screen.getByRole('button', { name: /New look/ });
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

    // The AI strip renders "Add {name} to finish this look".
    expect(screen.getByText(/recommended shoe/i)).toBeInTheDocument();
  });
});
