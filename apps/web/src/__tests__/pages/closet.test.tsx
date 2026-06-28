import { describe, it, expect, beforeEach, vi, type Mock } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import ClosetPage from '@/app/closet/page';
import { useClosetStore } from '@/stores/useClosetStore';
import type { ClosetItem } from '@tailor/contracts';

// The closet page calls useRouter()/usePathname() directly, which throw the
// "expected app router to be mounted" invariant without a provider — mock them.
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => '/closet',
  useSearchParams: () => new URLSearchParams(),
}));

// Route protection is covered by the auth-module tests; here we render as an
// authenticated user so we can assert the closet UI. Mocking the hook also keeps
// the Supabase client out of this test.
vi.mock('@/lib/auth/useRequireAuth', () => ({
  useRequireAuth: () => ({ session: { user: { id: 'u1' } }, loading: false }),
}));

// Mock the store
vi.mock('@/stores/useClosetStore', () => ({
  useClosetStore: vi.fn(),
}));

describe('ClosetPage', () => {
  const mockFetchItems = vi.fn();
  const mockAddItem = vi.fn();

  type StoreState = {
    items: ClosetItem[];
    hasFetchedItems: boolean;
    isLoading: boolean;
    fetchItems: typeof mockFetchItems;
    addItem: typeof mockAddItem;
  };

  function mockStore(partial: Partial<StoreState> = {}) {
    const state: StoreState = {
      items: [],
      hasFetchedItems: false,
      isLoading: false,
      fetchItems: mockFetchItems,
      addItem: mockAddItem,
      ...partial,
    };
    (useClosetStore as unknown as Mock).mockImplementation(
      (selector: (s: StoreState) => unknown) => selector(state)
    );
  }

  const storeItems: ClosetItem[] = [
    {
      id: '1',
      userId: 'user-1',
      name: 'Blue Shirt',
      category: 'top',
      createdAt: '2024-01-01T00:00:00Z',
      updatedAt: '2024-01-01T00:00:00Z',
    },
    {
      id: '2',
      userId: 'user-1',
      name: 'Black Jeans',
      category: 'bottom',
      createdAt: '2024-01-01T00:00:00Z',
      updatedAt: '2024-01-01T00:00:00Z',
    },
  ];

  beforeEach(() => {
    vi.clearAllMocks();
    mockStore();
  });

  it('renders the closet header', () => {
    render(<ClosetPage />);
    expect(screen.getByText('My Closet')).toBeInTheDocument();
  });

  it('renders the category filters', () => {
    render(<ClosetPage />);
    expect(screen.getByText('All')).toBeInTheDocument();
    expect(screen.getByText('Tops')).toBeInTheDocument();
    expect(screen.getByText('Shoes')).toBeInTheDocument();
  });

  it('shows the empty state when the store is empty', () => {
    // Post-e599895: an empty store renders the real empty state — no mock fallback.
    mockStore({ items: [], hasFetchedItems: true });
    render(<ClosetPage />);
    expect(screen.getByText('Your closet is empty')).toBeInTheDocument();
    expect(screen.queryByText('Beige Cardigan')).not.toBeInTheDocument();
  });

  it('renders real items from the store when present', () => {
    mockStore({ items: storeItems, hasFetchedItems: true });
    render(<ClosetPage />);
    expect(screen.getByText('Blue Shirt')).toBeInTheDocument();
    expect(screen.getByText('Black Jeans')).toBeInTheDocument();
  });

  it('calls fetchItems on mount when items have not been fetched yet', () => {
    mockStore({ items: [], hasFetchedItems: false });
    render(<ClosetPage />);
    expect(mockFetchItems).toHaveBeenCalled();
  });

  it('does not call fetchItems again once items have been fetched', () => {
    mockStore({ items: storeItems, hasFetchedItems: true });
    render(<ClosetPage />);
    expect(mockFetchItems).not.toHaveBeenCalled();
  });

  it('filters items by category when a filter is selected', async () => {
    const user = userEvent.setup();
    mockStore({ items: storeItems, hasFetchedItems: true });
    render(<ClosetPage />);

    // A top (Blue Shirt) and a bottom (Black Jeans) are visible initially.
    expect(screen.getByText('Blue Shirt')).toBeInTheDocument(); // top
    expect(screen.getByText('Black Jeans')).toBeInTheDocument(); // bottom

    await user.click(screen.getByText('Tops'));

    // After filtering to Tops, the bottom item is gone, the top remains.
    expect(screen.getByText('Blue Shirt')).toBeInTheDocument();
    expect(screen.queryByText('Black Jeans')).not.toBeInTheDocument();
  });
});
