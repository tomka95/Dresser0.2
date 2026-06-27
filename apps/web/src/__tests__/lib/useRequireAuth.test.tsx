import { describe, it, expect, beforeEach, vi } from 'vitest';
import { renderHook, waitFor, act } from '@testing-library/react';

// Router spy
const replace = vi.fn();
vi.mock('next/navigation', () => ({
  useRouter: () => ({ replace, push: vi.fn() }),
}));

// Controllable auth module: getSession is the authoritative initial resolver,
// onAuthStateChange captures the listener so tests can emit auth events.
const { getSession, onAuthStateChange, listeners } = vi.hoisted(() => {
  const listeners: Array<(event: string, session: unknown) => void> = [];
  return {
    listeners,
    getSession: vi.fn(),
    onAuthStateChange: vi.fn((cb: (event: string, session: unknown) => void) => {
      listeners.push(cb);
      return { unsubscribe: vi.fn() };
    }),
  };
});

vi.mock('@/lib/auth', () => ({ getSession, onAuthStateChange }));

import { useRequireAuth } from '@/lib/auth/useRequireAuth';

function emit(event: string, session: unknown) {
  listeners.forEach((cb) => cb(event, session));
}

describe('useRequireAuth', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    listeners.length = 0;
  });

  it('stays in the loading state and does NOT redirect while the session is unresolved', async () => {
    // getSession never resolves during this assertion window.
    let resolveSession: (value: unknown) => void = () => {};
    getSession.mockReturnValue(
      new Promise((res) => {
        resolveSession = res;
      })
    );

    const { result } = renderHook(() => useRequireAuth());

    expect(result.current.status).toBe('loading');
    expect(result.current.loading).toBe(true);
    expect(result.current.session).toBeNull();
    expect(replace).not.toHaveBeenCalled();

    // Resolve afterwards so the pending promise doesn't leak into other tests.
    await act(async () => {
      resolveSession({ user: { id: 'u' } });
    });
    expect(result.current.status).toBe('authenticated');
    expect(replace).not.toHaveBeenCalled();
  });

  it('resolves to authenticated and never redirects a logged-in user', async () => {
    getSession.mockResolvedValue({ user: { id: 'u' }, access_token: 't' });

    const { result } = renderHook(() => useRequireAuth());

    await waitFor(() => expect(result.current.status).toBe('authenticated'));
    expect(result.current.session).not.toBeNull();
    expect(replace).not.toHaveBeenCalled();
  });

  it('redirects to /sign-in only once the session definitively resolves to null', async () => {
    getSession.mockResolvedValue(null);

    const { result } = renderHook(() => useRequireAuth());

    await waitFor(() => expect(replace).toHaveBeenCalledWith('/sign-in'));
    expect(result.current.status).toBe('unauthenticated');
  });

  it('ignores INITIAL_SESSION(null) so a rehydrating logged-in user is not redirected', async () => {
    getSession.mockResolvedValue({ user: { id: 'u' } });

    const { result } = renderHook(() => useRequireAuth());
    await waitFor(() => expect(result.current.status).toBe('authenticated'));

    // A late INITIAL_SESSION carrying null must not flip us to unauthenticated.
    await act(async () => {
      emit('INITIAL_SESSION', null);
    });

    expect(result.current.status).toBe('authenticated');
    expect(replace).not.toHaveBeenCalled();
  });

  it('redirects when the user signs out after being authenticated', async () => {
    getSession.mockResolvedValue({ user: { id: 'u' } });

    const { result } = renderHook(() => useRequireAuth());
    await waitFor(() => expect(result.current.status).toBe('authenticated'));

    await act(async () => {
      emit('SIGNED_OUT', null);
    });

    await waitFor(() => expect(replace).toHaveBeenCalledWith('/sign-in'));
    expect(result.current.status).toBe('unauthenticated');
  });
});
