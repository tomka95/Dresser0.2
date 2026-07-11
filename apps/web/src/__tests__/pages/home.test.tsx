import { describe, it, expect, beforeEach, vi, type Mock } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';

// ── Mocks (mirrors closet.test.tsx / review.test.tsx) ────────────────────────
// Home calls useRouter()/usePathname() directly and would otherwise throw the
// app-router invariant.
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn() }),
  usePathname: () => '/home',
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock('@/lib/auth/useRequireAuth', () => ({
  useRequireAuth: () => ({ session: { user: { id: 'u1', user_metadata: {} } }, loading: false }),
}));

// Store: home reads items / fetchItems / hasFetchedItems via selectors.
vi.mock('@/stores/useClosetStore', () => ({ useClosetStore: vi.fn() }));
import { useClosetStore } from '@/stores/useClosetStore';

// Keep the bento / today's-look / feed off this test: offline collapses Home to the
// greeting + banner + a static OfflineScreen, so the banner is exercised in isolation
// and no feed/weather/calendar/today's-look network is touched.
vi.mock('@/lib/useOnline', () => ({ useOnline: () => false }));

vi.mock('@/lib/api/auth', () => ({
  getCurrentUser: vi.fn().mockResolvedValue({ display_name: 'Guy', full_name: 'Guy K' }),
}));

vi.mock('@/lib/api/shop', () => ({
  getShopFeed: vi.fn().mockResolvedValue({ cards: [], framing: 'personalized', cursor: 0, hasMore: false }),
  mintClick: vi.fn(),
  ShopAuthError: class ShopAuthError extends Error {},
}));

vi.mock('@/lib/api/weather', () => ({
  getWeather: vi.fn().mockResolvedValue({ available: false }),
  getCachedWeather: () => null,
  isWeatherFresh: () => false,
}));

vi.mock('@/lib/api/calendar', () => ({
  getCalendarToday: vi.fn().mockResolvedValue({ connected: false, events: [] }),
  getCachedCalendarToday: () => null,
  isCalendarFresh: () => false,
}));

vi.mock('@/lib/api/events', () => ({ logEvent: vi.fn() }));

// The API under test — controlled per test.
const getPendingReview = vi.fn();
const ackPendingReview = vi.fn();
vi.mock('@/lib/api/gmail', () => ({
  getPendingReview: () => getPendingReview(),
  ackPendingReview: (syncId: string, action: string) => ackPendingReview(syncId, action),
}));

import HomePage from '@/app/home/page';

interface ClosetState {
  items: unknown[];
  hasFetchedItems: boolean;
  fetchItems: () => void;
}

function mockCloset() {
  const state: ClosetState = { items: [], hasFetchedItems: true, fetchItems: vi.fn() };
  (useClosetStore as unknown as Mock).mockImplementation((selector: (s: ClosetState) => unknown) =>
    selector(state),
  );
}

describe('HomePage — review-ready banner', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockCloset();
  });

  it('renders the banner with the ready count when a scan is pending', async () => {
    getPendingReview.mockResolvedValue({ pending: true, sync_id: 's1', ready_count: 3 });

    render(<HomePage />);

    expect(await screen.findByText('3 items ready to review')).toBeInTheDocument();
  });

  it('does not render the banner when nothing is pending', async () => {
    getPendingReview.mockResolvedValue({ pending: false, sync_id: null, ready_count: 0 });

    render(<HomePage />);

    // Wait until the pending-review read has resolved, then assert no banner.
    await waitFor(() => expect(getPendingReview).toHaveBeenCalled());
    expect(screen.queryByText(/ready to review/i)).toBeNull();
  });
});
