import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import ClosetPage from '@/app/closet/page';
import { useClosetStore } from '@/stores/useClosetStore';
import type { ClosetItem } from '@dresser/contracts';

// Mock the store
vi.mock('@/stores/useClosetStore', () => ({
  useClosetStore: vi.fn(),
}));

// Mock analytics
vi.mock('@/lib/analytics', () => ({
  track: vi.fn(),
}));

describe('ClosetPage', () => {
  const mockFetchItems = vi.fn();
  const mockAddItem = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(useClosetStore).mockImplementation((selector) => {
      const state = {
        items: [] as ClosetItem[],
        isLoading: false,
        error: undefined as string | undefined,
        fetchItems: mockFetchItems,
        addItem: mockAddItem,
      };
      return selector(state);
    });
  });

  it('should render empty state when no items', () => {
    render(<ClosetPage />);

    expect(screen.getByText('Your closet is empty')).toBeInTheDocument();
    expect(
      screen.getByText('Start by adding your first clothing item')
    ).toBeInTheDocument();
  });

  it('should render loading state', () => {
    vi.mocked(useClosetStore).mockImplementation((selector) => {
      const state = {
        items: [],
        isLoading: true,
        error: undefined,
        fetchItems: mockFetchItems,
        addItem: mockAddItem,
      };
      return selector(state);
    });

    render(<ClosetPage />);

    expect(screen.getByText('Loading closet…')).toBeInTheDocument();
  });

  it('should render error state', () => {
    vi.mocked(useClosetStore).mockImplementation((selector) => {
      const state = {
        items: [],
        isLoading: false,
        error: 'Network error',
        fetchItems: mockFetchItems,
        addItem: mockAddItem,
      };
      return selector(state);
    });

    render(<ClosetPage />);

    expect(screen.getByText(/Network error/)).toBeInTheDocument();
  });

  it('should render closet items', () => {
    const mockItems: ClosetItem[] = [
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

    vi.mocked(useClosetStore).mockImplementation((selector) => {
      const state = {
        items: mockItems,
        isLoading: false,
        error: undefined,
        fetchItems: mockFetchItems,
        addItem: mockAddItem,
      };
      return selector(state);
    });

    render(<ClosetPage />);

    expect(screen.getByText('Blue Shirt')).toBeInTheDocument();
    expect(screen.getByText('Black Jeans')).toBeInTheDocument();
    expect(screen.getByText('top')).toBeInTheDocument();
    expect(screen.getByText('bottom')).toBeInTheDocument();
  });

  it('should call fetchItems on mount when items are empty', () => {
    render(<ClosetPage />);

    expect(mockFetchItems).toHaveBeenCalled();
  });

  it('should not call fetchItems if items already exist', () => {
    const mockItems: ClosetItem[] = [
      {
        id: '1',
        userId: 'user-1',
        name: 'Item',
        category: 'top',
        createdAt: '2024-01-01T00:00:00Z',
        updatedAt: '2024-01-01T00:00:00Z',
      },
    ];

    vi.mocked(useClosetStore).mockImplementation((selector) => {
      const state = {
        items: mockItems,
        isLoading: false,
        error: undefined,
        fetchItems: mockFetchItems,
        addItem: mockAddItem,
      };
      return selector(state);
    });

    render(<ClosetPage />);

    // fetchItems should not be called again since items exist
    expect(mockFetchItems).not.toHaveBeenCalled();
  });

  it('should handle add item button click', async () => {
    const user = userEvent.setup();

    render(<ClosetPage />);

    const addButton = screen.getByText('Add Sample Item');
    await user.click(addButton);

    expect(mockAddItem).toHaveBeenCalledWith({
      name: expect.stringContaining('Sample Item'),
      category: 'other',
      color: 'mixed tones',
      brand: 'Dresser Mock',
    });
  });

  it('should disable add button when loading', () => {
    vi.mocked(useClosetStore).mockImplementation((selector) => {
      const state = {
        items: [],
        isLoading: true,
        error: undefined,
        fetchItems: mockFetchItems,
        addItem: mockAddItem,
      };
      return selector(state);
    });

    render(<ClosetPage />);

    const addButton = screen.getByText('Add Sample Item');
    expect(addButton).toBeDisabled();
  });
});





