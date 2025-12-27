import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import ItemDetailsPage from '@/app/closet/[id]/page';
import { useClosetStore } from '@/stores/useClosetStore';
import type { ClosetItem } from '@tailor/contracts';

// Mock next/navigation
vi.mock('next/navigation', () => ({
  useRouter: () => ({
    push: vi.fn(),
  }),
}));

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
      });
    });

    render(<ItemDetailsPage params={{ id: itemId }} />);
    expect(screen.getByText('Loading item details...')).toBeInTheDocument();
  });

  it('renders item details after loading', async () => {
    render(<ItemDetailsPage params={{ id: itemId }} />);

    await waitFor(() => {
      expect(screen.getByDisplayValue('Test Item')).toBeInTheDocument();
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
      expect(screen.getByDisplayValue('Test Item')).toBeInTheDocument();
    });

    const nameInput = screen.getByLabelText('Item Name');
    await user.clear(nameInput);
    await user.type(nameInput, 'Updated Name');

    expect(nameInput).toHaveValue('Updated Name');
  });

  it('saves changes calls updateItem with name', async () => {
    const user = userEvent.setup();
    render(<ItemDetailsPage params={{ id: itemId }} />);

    await waitFor(() => {
      expect(screen.getByDisplayValue('Test Item')).toBeInTheDocument();
    });

    // Change name
    const nameInput = screen.getByLabelText('Item Name');
    await user.clear(nameInput);
    await user.type(nameInput, 'Updated Name');

    // Save
    const saveButton = screen.getByText('Save Changes');
    await user.click(saveButton);

    expect(mockUpdateItem).toHaveBeenCalledWith(itemId, {
      name: 'Updated Name',
    });
  });

  it('displays validation errors from store', async () => {
    const errorMsg = 'Validation failed';
    mockUpdateItem.mockRejectedValue(new Error(errorMsg));
    
    const user = userEvent.setup();
    render(<ItemDetailsPage params={{ id: itemId }} />);

    await waitFor(() => {
      expect(screen.getByDisplayValue('Test Item')).toBeInTheDocument();
    });

    const saveButton = screen.getByText('Save Changes');
    await user.click(saveButton);

    await waitFor(() => {
      expect(screen.getByText(errorMsg)).toBeInTheDocument();
    });
  });
});

