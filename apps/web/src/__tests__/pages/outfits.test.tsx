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

// The page navigates (outfit cards → /outfits/[id]).
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), back: vi.fn() }),
  usePathname: () => '/outfits',
}));

// Auth guard: the component destructures { session, loading } and gates on
// `loading || !session`, so the mock must resolve to an authenticated,
// non-loading session (mirrors review.test.tsx).
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

// Mock analytics + the worn-feedback client ("Wore it" posts /outfits/feedback).
vi.mock('@/lib/analytics', () => ({
  track: vi.fn(),
}));

vi.mock('@/lib/api/outfitFeedback', () => ({
  sendOutfitFeedback: vi.fn().mockResolvedValue({ ok: true }),
}));

const CLOSET_ITEM: ClosetItem = {
  id: 'item-1',
  userId: 'user-1',
  name: 'Blue Shirt',
  category: 'top',
  imageUrl: 'https://example.com/shirt.jpg',
  createdAt: '2024-01-01T00:00:00.000Z',
  updatedAt: '2024-01-01T00:00:00.000Z',
};

function outfitFixture(overrides: Partial<OutfitSuggestion> = {}): OutfitSuggestion {
  return {
    id: '0f6f5c1e-6a1a-4c39-9a10-000000000001',
    userId: 'user-1',
    name: 'Weekend Look',
    occasion: 'Casual',
    items: [CLOSET_ITEM.id],
    rationale: null,
    source: 'composer',
    status: 'active',
    isLiked: false,
    createdAt: '2024-01-01T00:00:00.000Z',
    ...overrides,
  };
}

describe('OutfitsPage', () => {
  const mockFetchOutfits = vi.fn();
  const mockGenerateOutfit = vi.fn().mockResolvedValue(true);
  const mockToggleLike = vi.fn();
  const mockUnsave = vi.fn();
  const mockFetchClosetItems = vi.fn();

  type OutfitsStoreSlice = {
    outfits: OutfitSuggestion[];
    likedOutfits: string[];
    isLoading: boolean;
    isGenerating: boolean;
    error?: string;
    generateNotice?: string;
    fetchOutfits: typeof mockFetchOutfits;
    generateOutfit: typeof mockGenerateOutfit;
    toggleLike: typeof mockToggleLike;
    unsave: typeof mockUnsave;
  };

  function mockOutfitsState(overrides: Partial<OutfitsStoreSlice> = {}) {
    const state: OutfitsStoreSlice = {
      outfits: [],
      likedOutfits: [],
      isLoading: false,
      isGenerating: false,
      error: undefined,
      generateNotice: undefined,
      fetchOutfits: mockFetchOutfits,
      generateOutfit: mockGenerateOutfit,
      toggleLike: mockToggleLike,
      unsave: mockUnsave,
      ...overrides,
    };
    vi.mocked(useOutfitsStore).mockImplementation((selector) => selector(state));
    (useOutfitsStore as unknown as { getState?: () => OutfitsStoreSlice }).getState =
      () => state;
  }

  function mockClosetState(items: ClosetItem[] = [], isLoading = false) {
    (useClosetStore as unknown as Mock).mockImplementation(
      (selector: (s: ClosetStoreSlice) => unknown) =>
        selector({ items, isLoading, fetchItems: mockFetchClosetItems })
    );
  }

  beforeEach(() => {
    vi.clearAllMocks();
    mockGenerateOutfit.mockResolvedValue(true);
    mockOutfitsState();
    mockClosetState();
  });

  it('should render empty state when no outfits', () => {
    render(<OutfitsPage />);

    expect(screen.getByText('No outfits yet')).toBeInTheDocument();
    expect(screen.getByText('Style me for today')).toBeInTheDocument();
  });

  it('should render loading state', () => {
    mockOutfitsState({ isLoading: true });

    render(<OutfitsPage />);

    // Skeleton list (aria-hidden) + the header "New look" button only.
    expect(screen.queryByText('No outfits yet')).not.toBeInTheDocument();
    const buttons = screen.getAllByRole('button');
    expect(buttons).toHaveLength(1);
  });

  it('should render error state', () => {
    mockOutfitsState({ error: 'Failed to load' });

    render(<OutfitsPage />);

    expect(screen.getByText(/Failed to load/)).toBeInTheDocument();
  });

  it('should render outfits whose items resolve to real closet items', () => {
    mockOutfitsState({ outfits: [outfitFixture()] });
    mockClosetState([CLOSET_ITEM]);

    render(<OutfitsPage />);

    expect(screen.getByText('Weekend Look')).toBeInTheDocument();
    expect(screen.getByText('Casual')).toBeInTheDocument();
    // Item previews render as image thumbnails (alt = item name).
    expect(screen.getByAltText('Blue Shirt')).toBeInTheDocument();
  });

  it('should NOT render an outfit whose items no longer resolve to the closet', () => {
    // Real closet is loaded but the outfit references a deleted item — the card
    // must not render as an empty placeholder (honest-rendering rule).
    mockOutfitsState({
      outfits: [outfitFixture({ items: ['gone-item'], name: 'Ghost Look' })],
    });
    mockClosetState([CLOSET_ITEM]);

    render(<OutfitsPage />);

    expect(screen.queryByText('Ghost Look')).not.toBeInTheDocument();
    expect(screen.getByText('No outfits yet')).toBeInTheDocument();
  });

  it('should call fetchOutfits on mount when outfits are empty', () => {
    render(<OutfitsPage />);

    expect(mockFetchOutfits).toHaveBeenCalled();
  });

  it('should handle like button click', async () => {
    const outfit = outfitFixture();
    mockOutfitsState({ outfits: [outfit] });
    mockClosetState([CLOSET_ITEM]);

    render(<OutfitsPage />);

    const likeButton = screen.getByRole('button', { name: 'Like outfit' });
    const user = userEvent.setup();
    await user.click(likeButton);

    expect(mockToggleLike).toHaveBeenCalledWith(outfit.id);
  });

  it('should show liked state when outfit is liked', () => {
    const outfit = outfitFixture({ isLiked: true });
    mockOutfitsState({ outfits: [outfit], likedOutfits: [outfit.id] });
    mockClosetState([CLOSET_ITEM]);

    render(<OutfitsPage />);

    expect(screen.getByRole('button', { name: 'Unlike outfit' })).toBeInTheDocument();
  });

  it('should generate a new look via the real endpoint', async () => {
    const user = userEvent.setup();

    render(<OutfitsPage />);

    const generateButton = screen.getByRole('button', { name: /Style me for today/ });
    await user.click(generateButton);

    expect(mockGenerateOutfit).toHaveBeenCalled();
  });

  it('should surface the honest composer gap note', () => {
    mockOutfitsState({
      generateNotice: 'Your closet is missing a footwear for this.',
    });

    render(<OutfitsPage />);

    expect(
      screen.getByText(/Your closet is missing a footwear/)
    ).toBeInTheDocument();
  });
});
