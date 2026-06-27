import { describe, it, expect, beforeEach, vi } from 'vitest';

// Fake supabase auth surface. Defined via vi.hoisted so it exists when the
// (hoisted) vi.mock factory runs.
const { auth } = vi.hoisted(() => ({
  auth: {
    getSession: vi.fn(),
    getUser: vi.fn(),
    signInWithPassword: vi.fn(),
    signUp: vi.fn(),
    signInWithOAuth: vi.fn(),
    signOut: vi.fn(),
    onAuthStateChange: vi.fn(() => ({
      data: { subscription: { unsubscribe: vi.fn() } },
    })),
  },
}));

vi.mock('@/lib/supabase/client', () => ({
  getSupabaseClient: () => ({ auth }),
}));

import {
  getAccessToken,
  isAuthenticated,
  signOut,
  signInWithProvider,
  signInWithPassword,
  signUpWithPassword,
} from '@/lib/auth';

beforeEach(() => {
  vi.clearAllMocks();
});

describe('auth module', () => {
  it('getAccessToken returns the session access token', async () => {
    auth.getSession.mockResolvedValue({
      data: { session: { access_token: 'token-123' } },
    });
    expect(await getAccessToken()).toBe('token-123');
  });

  it('getAccessToken / isAuthenticated handle no session', async () => {
    auth.getSession.mockResolvedValue({ data: { session: null } });
    expect(await getAccessToken()).toBeNull();
    expect(await isAuthenticated()).toBe(false);
  });

  it('signInWithPassword surfaces supabase errors', async () => {
    auth.signInWithPassword.mockResolvedValue({
      data: {},
      error: { message: 'Invalid login credentials' },
    });
    await expect(
      signInWithPassword({ email: 'a@b.com', password: 'x' })
    ).rejects.toThrow('Invalid login credentials');
  });

  it('signInWithProvider maps the id and redirects to /auth/callback (no Gmail scope)', async () => {
    auth.signInWithOAuth.mockResolvedValue({ data: {}, error: null });
    await signInWithProvider('google');
    expect(auth.signInWithOAuth).toHaveBeenCalledTimes(1);
    const arg = auth.signInWithOAuth.mock.calls[0][0];
    expect(arg.provider).toBe('google');
    expect(arg.options.redirectTo).toContain('/auth/callback');
    // Login only: we must not request Gmail (or any) extra scopes here.
    expect(arg.options.scopes).toBeUndefined();
  });

  it('signUpWithPassword reports email-confirmation when no session is returned', async () => {
    auth.signUp.mockResolvedValue({
      data: { session: null, user: { id: 'u1' } },
      error: null,
    });
    const result = await signUpWithPassword({
      email: 'new@b.com',
      password: 'pw',
      fullName: 'New User',
    });
    expect(result.needsEmailConfirmation).toBe(true);
    const arg = auth.signUp.mock.calls[0][0];
    expect(arg.email).toBe('new@b.com');
    expect(arg.options.data).toEqual({ full_name: 'New User' });
  });

  it('signOut delegates to supabase', async () => {
    auth.signOut.mockResolvedValue({ error: null });
    await signOut();
    expect(auth.signOut).toHaveBeenCalledTimes(1);
  });
});
