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
  // Read-only connection context for the empty state; resolved as connected here.
  fetchGmailConnectionStatus: vi.fn().mockResolvedValue({ connected: true, scope: null, connected_at: null }),
  startGmailConnect: vi.fn(),
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
    generated_image_url: null, generation_status: null,
    confidence_overall: 0.92, low_confidence_fields: [], seen_count: 1,
    source_type: 'gmail',
    source: { merchant: 'Levi', order_id: null, message_id: 'm1', google_account_id: 1, email_date: null },
  },
  {
    candidate_id: 'c2', name: 'Mystery Tee', brand: null, category: 'top',
    color: null, size: null, qty: 1, unit_price: null, currency: null,
    order_date: null, is_return: false,
    image_url: null, image_status: 'pending',
    generated_image_url: null, generation_status: null,
    confidence_overall: null, low_confidence_fields: ['brand', 'unit_price'], seen_count: 1,
    source_type: 'gmail',
    source: { merchant: null, order_id: null, message_id: 'm2', google_account_id: 1, email_date: null },
  },
];

// A photo candidate: category + color, NO price / NO brand — must degrade gracefully.
const PHOTO_ONLY: IngestCandidate[] = [
  {
    candidate_id: 'p1', name: 'Wide-leg Jeans', brand: null, category: 'bottom',
    color: 'Olive', size: 'M', qty: 1, unit_price: null, currency: null,
    order_date: null, is_return: false,
    image_url: 'https://example.com/photo.jpg', image_status: 'user_uploaded',
    generated_image_url: null, generation_status: null,
    confidence_overall: 0.8, low_confidence_fields: [], seen_count: 1,
    source_type: 'photo',
    source: { merchant: null, order_id: null, message_id: null, google_account_id: null, email_date: null },
  },
];

describe('ReviewPage deck card', () => {
  it('renders gmail card with data-driven Label/Value chips (incl. Price)', async () => {
    getIngestCandidates.mockResolvedValue(CANDIDATES);
    render(<ReviewPage />);
    // mount loads candidates async → wait for the first card body.
    expect(await screen.findByText("Levi's 501")).toBeInTheDocument();
    expect(screen.getByText('92%')).toBeInTheDocument();
    // Populated chips render as Label + Value.
    expect(screen.getByText('Category')).toBeInTheDocument();
    expect(screen.getByText('Bottom')).toBeInTheDocument();
    expect(screen.getByText('Color')).toBeInTheDocument();
    expect(screen.getByText('Indigo')).toBeInTheDocument();
    expect(screen.getByText('Price')).toBeInTheDocument();
    expect(screen.getByText('$98.00')).toBeInTheDocument();
    // Gmail source badge.
    expect(screen.getByText(/Detected in Gmail/)).toBeInTheDocument();
  });

  it('photo card degrades gracefully: category/color/size chips, NO Price chip', async () => {
    getIngestCandidates.mockResolvedValue(PHOTO_ONLY);
    render(<ReviewPage />);
    expect(await screen.findByText('Wide-leg Jeans')).toBeInTheDocument();
    // Populated chips present…
    expect(screen.getByText('Color')).toBeInTheDocument();
    expect(screen.getByText('Olive')).toBeInTheDocument();
    expect(screen.getByText('Size')).toBeInTheDocument();
    // …but no price data → the Price chip must NOT render (no blank "Price $").
    expect(screen.queryByText('Price')).toBeNull();
    // Source-aware badge for photo.
    expect(screen.getByText(/From your photo/)).toBeInTheDocument();
  });

  it('renders the card image visibly with the candidate src, in a width-derived aspect box', async () => {
    getIngestCandidates.mockResolvedValue(CANDIDATES);
    const { container } = render(<ReviewPage />);
    await screen.findByText("Levi's 501");

    // The loaded cutout paints: <img> present, correct src, not hidden/display:none.
    const img = screen.getByRole('img', { name: "Levi's 501" });
    expect(img).toHaveAttribute('src', 'https://example.com/a.jpg');
    expect(img).toBeVisible();

    // The image container is a width-derived aspect box → definite height, no dependency
    // on the ancestor min-h-full/h-full chain, so it can't collapse to 0.
    expect(container.querySelector('[class*="aspect-["]')).not.toBeNull();
  });
});
