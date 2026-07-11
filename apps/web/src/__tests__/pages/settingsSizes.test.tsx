import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), back: vi.fn() }),
  usePathname: () => '/settings/sizes',
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

import SizesFitPage from '@/app/settings/sizes/page';

const LEGACY_KEY = 'tailor.pref.sizes';

describe('Sizes & fit screen — facts as source of truth', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.localStorage.clear();
  });

  it('renders sizes mapped from server facts (structured SizeProfile)', async () => {
    getStyleProfile.mockResolvedValue({
      facts: {
        sizes: { top: 'L', bottom: { system: 'waist_inseam', waist: 34 }, shoe: { system: 'EU', value: '44' } },
        fit_preference: 'Slim',
      },
      narrative: null, summary: null, onboardingCompletedAt: null, version: 1, preferences: [],
    });
    render(<SizesFitPage />);
    // 'L' (tops) and 'EU 44' (shoes) come straight from the structured facts.
    expect(await screen.findByText('L')).toBeTruthy();
    expect(screen.getByText('EU 44')).toBeTruthy();
    expect(screen.getByText('34')).toBeTruthy();
  });

  it('migrates the legacy localStorage key to the server, then discards it', async () => {
    // Server has no sizes yet; a legacy device-only copy exists.
    getStyleProfile.mockResolvedValue({
      facts: {}, narrative: null, summary: null, onboardingCompletedAt: null, version: 0, preferences: [],
    });
    window.localStorage.setItem(
      LEGACY_KEY,
      JSON.stringify({ sizes: { tops: 'S', bottoms: '30', shoes: 'EU 41', outerwear: 'S' }, fit: 'Relaxed' }),
    );
    patchStyleProfile.mockResolvedValue({
      facts: {
        sizes: { top: 'S', bottom: { system: 'waist_inseam', waist: 30 }, shoe: { system: 'EU', value: '41' } },
        fit_preference: 'Relaxed',
      },
      narrative: null, summary: null, onboardingCompletedAt: null, version: 1, preferences: [],
    });

    render(<SizesFitPage />);

    await waitFor(() => {
      expect(patchStyleProfile).toHaveBeenCalledWith({
        facts: {
          sizes: { top: 'S', outerwear: 'S', bottom: { system: 'waist_inseam', waist: 30 }, shoe: { system: 'EU', value: '41' } },
          fit_preference: 'Relaxed',
        },
      });
    });
    // Legacy device-only key is gone — no more divergence.
    expect(window.localStorage.getItem(LEGACY_KEY)).toBeNull();
  });
});
