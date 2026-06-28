import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import type { IngestCandidate } from '@/lib/api/gmail';

// Mirrors closet.test.tsx: useRouter()/the auth hook/the store throw or pull in
// supabase-js without these mocks. Route protection is covered elsewhere; render
// as an authenticated user so the deck itself is exercised.
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn() }),
  usePathname: () => '/review',
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock('@/lib/auth/useRequireAuth', () => ({
  useRequireAuth: () => ({ session: { user: { id: 'u1' } }, status: 'authenticated', loading: false }),
}));

vi.mock('@/stores/useClosetStore', () => ({
  useClosetStore: Object.assign(vi.fn(), { getState: () => ({ invalidate: vi.fn() }) }),
}));

const getIngestCandidates = vi.fn();
vi.mock('@/lib/api/gmail', () => ({
  getIngestCandidates: () => getIngestCandidates(),
  getIngestStatus: vi.fn(),
  startIngest: vi.fn(),
  confirmCandidates: vi.fn(),
}));

import ReviewPage from '@/app/review/page';

// A fully-populated candidate followed by a null-heavy one (null price, null
// order_date, null image, null brand/color/size, null confidence) — the exact
// shape that previously risked a blank/throwing card. The deck must render the
// body for both and never throw on a missing field.
const CANDIDATES: IngestCandidate[] = [
  {
    candidate_id: 'c1', name: "Levi's 501", brand: "Levi's", category: 'bottom',
    color: 'Indigo', size: '32', qty: 1, unit_price: 98, currency: 'USD',
    order_date: '2026-01-02', is_return: false,
    image_url: 'https://example.com/a.jpg', image_status: 'resolved',
    confidence_overall: 0.92, low_confidence_fields: [], seen_count: 1,
    source: { merchant: 'Levi', order_id: null, message_id: 'm1', google_account_id: 1, email_date: null },
  },
  {
    candidate_id: 'c2', name: 'Mystery Tee', brand: null, category: 'top',
    color: null, size: null, qty: 1, unit_price: null, currency: null,
    order_date: null, is_return: false,
    image_url: null, image_status: 'pending',
    confidence_overall: null, low_confidence_fields: ['brand', 'unit_price'], seen_count: 1,
    source: { merchant: null, order_id: null, message_id: 'm2', google_account_id: 1, email_date: null },
  },
];

describe('ReviewPage deck card', () => {
  it('renders the card body (name + category chip) without throwing on null fields', async () => {
    getIngestCandidates.mockResolvedValue(CANDIDATES);
    render(<ReviewPage />);
    // mount loads candidates async → wait for the first card body.
    expect(await screen.findByText("Levi's 501")).toBeInTheDocument();
    expect(screen.getByText('Bottom')).toBeInTheDocument(); // capitalized category chip
    expect(screen.getByText('92%')).toBeInTheDocument();
  });
});
