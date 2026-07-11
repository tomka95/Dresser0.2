import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), back: vi.fn() }),
  usePathname: () => '/settings/style',
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock('@/lib/auth/useRequireAuth', () => ({
  useRequireAuth: () => ({ session: { user: { id: 'u1' } }, loading: false }),
}));

const getStyleProfile = vi.fn();
const patchStyleProfile = vi.fn();
vi.mock('@/lib/api/profile', () => ({
  getStyleProfile: () => getStyleProfile(),
  patchStyleProfile: (patch: unknown) => patchStyleProfile(patch),
}));

import StyleProfilePage from '@/app/settings/style/page';

const PROFILE = {
  facts: { sizes: { top: 'M' } },
  narrative: 'Quiet minimal — neutral palette, relaxed fits.',
  summary: 'Quiet minimal',
  onboardingCompletedAt: '2026-06-01T00:00:00Z',
  version: 4,
  preferences: [
    {
      dimension: 'color',
      value: { notes: ['neutrals'] },
      polarity: 'like',
      confidence: 0.94,
      evidenceCount: 212,
      source: 'inferred',
      userEdited: false,
      lastReinforcedAt: null,
      explanation: 'Learned from 212 signals in your activity',
    },
  ],
};

describe('My Style Profile screen', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    getStyleProfile.mockResolvedValue(JSON.parse(JSON.stringify(PROFILE)));
  });

  it('renders the real narrative and a learned preference with its explanation', async () => {
    render(<StyleProfilePage />);
    expect(await screen.findByText(PROFILE.narrative)).toBeTruthy();
    expect(screen.getByText('Learned from 212 signals in your activity')).toBeTruthy();
    // The forget affordance for the learned dimension is present.
    expect(screen.getByRole('button', { name: /Forget: Color/ })).toBeTruthy();
  });

  it('renders an honest empty state for a fresh, sparse profile', async () => {
    getStyleProfile.mockResolvedValue({
      facts: {}, narrative: null, summary: null, onboardingCompletedAt: null, version: 0, preferences: [],
    });
    render(<StyleProfilePage />);
    expect(await screen.findByText(/Still learning your style/)).toBeTruthy();
    // No fabricated "in one line" narrative card.
    expect(screen.queryByText(/In one line/)).toBeNull();
  });

  it('delete calls PATCH with a tombstone and drops the row', async () => {
    patchStyleProfile.mockResolvedValue({ ...PROFILE, preferences: [] });
    render(<StyleProfilePage />);
    const forget = await screen.findByRole('button', { name: /Forget: Color/ });
    await userEvent.click(forget);
    await waitFor(() => {
      expect(patchStyleProfile).toHaveBeenCalledWith({ preferences: [{ dimension: 'color', delete: true }] });
    });
    await waitFor(() => expect(screen.getByText(/Still learning your style/)).toBeTruthy());
  });
});
