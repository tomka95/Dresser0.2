import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import ItemDetailsPage from '@/app/closet/[id]/page';
import { useClosetStore } from '@/stores/useClosetStore';

// Mock next/navigation
vi.mock('next/navigation', () => ({
  useRouter: () => ({
    push: vi.fn(),
    replace: vi.fn(),
    back: vi.fn(),
  }),
  // AppShell now renders BackgroundTailorNotice, which reads usePathname.
  usePathname: () => '/closet/x',
}));

// Render as authenticated; the three-state guard is covered by useRequireAuth.test.
// Return a STABLE object (created once in the factory) so `session`'s identity is
// constant across renders — the page's seed effect depends on `session`, and a
// fresh object each render would re-run it and clobber typed input. This mirrors
// how the real hook keeps the session reference stable between renders.
vi.mock('@/lib/auth/useRequireAuth', () => {
  const authState = {
    session: { user: { id: 'u1' } },
    status: 'authenticated' as const,
    loading: false,
  };
  return { useRequireAuth: () => authState };
});

// Mock the store
vi.mock('@/stores/useClosetStore', () => ({
  useClosetStore: vi.fn(),
}));

describe('ItemDetailsPage', () => {
  const mockFetchItem = vi.fn();
  const mockUpdateItem = vi.fn();
  const itemId = 'test-item-id';

  beforeEach(() => {
    vi.clearAllMocks();
    mockFetchItem.mockResolvedValue({
      id: itemId,
      name: 'Test Item',
      category: 'top',
      imageUrl: 'http://example.com/image.png',
    });
    mockUpdateItem.mockResolvedValue({
      id: itemId,
      name: 'Updated Name',
    });

    vi.mocked(useClosetStore).mockImplementation((selector) => {
      const state = {
        items: [],
        isLoading: false,
        isItemLoading: { [itemId]: false },
        hydratedItemIds: {},
        hasFetchedItems: false,
        error: undefined,
        fetchItem: mockFetchItem,
        updateItem: mockUpdateItem,
        fetchItems: vi.fn(),
        addItem: vi.fn(),
        invalidate: vi.fn(),
      };
      return selector(state);
    });
  });

  it('renders loading state', () => {
    vi.mocked(useClosetStore).mockImplementation((selector) => {
      return selector({
        items: [],
        isLoading: false,
        isItemLoading: { [itemId]: true },
        hydratedItemIds: {},
        hasFetchedItems: false,
        error: undefined,
        fetchItem: mockFetchItem,
        updateItem: mockUpdateItem,
        fetchItems: vi.fn(),
        addItem: vi.fn(),
        invalidate: vi.fn(),
      });
    });

    render(<ItemDetailsPage params={{ id: itemId }} />);
    expect(screen.getByRole('status', { name: 'Loading item' })).toBeInTheDocument();
  });

  it('renders item details after loading', async () => {
    render(<ItemDetailsPage params={{ id: itemId }} />);

    // Name renders as the hero title once the fetch resolves.
    await waitFor(() => {
      expect(screen.getByRole('heading', { name: 'Test Item' })).toBeInTheDocument();
    });

    expect(screen.getByAltText('Test Item')).toBeInTheDocument();
  });

  it('calls fetchItem on mount', () => {
    render(<ItemDetailsPage params={{ id: itemId }} />);
    expect(mockFetchItem).toHaveBeenCalledWith(itemId);
  });

  it('allows editing name', async () => {
    const user = userEvent.setup();
    render(<ItemDetailsPage params={{ id: itemId }} />);

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: 'Test Item' })).toBeInTheDocument();
    });

    // Inline edit: the pencil toggles the field row into an input.
    await user.click(screen.getByRole('button', { name: 'Edit name' }));
    const nameInput = screen.getByLabelText('Name');
    await user.clear(nameInput);
    await user.type(nameInput, 'Updated Name');

    expect(nameInput).toHaveValue('Updated Name');
  });

  it('saves changes calls updateItem with name', async () => {
    const user = userEvent.setup();
    render(<ItemDetailsPage params={{ id: itemId }} />);

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: 'Test Item' })).toBeInTheDocument();
    });

    // Change name via the inline editor
    await user.click(screen.getByRole('button', { name: 'Edit name' }));
    const nameInput = screen.getByLabelText('Name');
    await user.clear(nameInput);
    await user.type(nameInput, 'Updated Name');

    // Save
    const saveButton = screen.getByText('Save changes');
    await user.click(saveButton);

    expect(mockUpdateItem).toHaveBeenCalledWith(
      itemId,
      expect.objectContaining({ name: 'Updated Name' })
    );
  });

  it('displays validation errors from store', async () => {
    const errorMsg = 'Validation failed';
    mockUpdateItem.mockRejectedValue(new Error(errorMsg));

    const user = userEvent.setup();
    render(<ItemDetailsPage params={{ id: itemId }} />);

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: 'Test Item' })).toBeInTheDocument();
    });

    const saveButton = screen.getByText('Save changes');
    await user.click(saveButton);

    await waitFor(() => {
      expect(screen.getByText(errorMsg)).toBeInTheDocument();
    });
  });
});
