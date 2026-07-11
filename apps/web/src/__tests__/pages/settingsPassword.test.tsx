import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), back: vi.fn() }),
  usePathname: () => '/settings/password',
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock('@/lib/auth/useRequireAuth', () => ({
  useRequireAuth: () => ({
    session: { user: { id: 'u1', email: 'me@example.com' } },
    loading: false,
  }),
}));

const verifyCurrentPassword = vi.fn();
const updatePassword = vi.fn();
vi.mock('@/lib/auth', () => ({
  verifyCurrentPassword: (email: string, pw: string) => verifyCurrentPassword(email, pw),
  updatePassword: (pw: string) => updatePassword(pw),
}));

import ChangePasswordPage from '@/app/settings/password/page';

function fillForm({ current, next, confirm }: { current: string; next: string; confirm: string }) {
  fireEvent.change(screen.getByPlaceholderText('••••••••'), { target: { value: current } });
  fireEvent.change(screen.getByPlaceholderText('••••••••••'), { target: { value: next } });
  fireEvent.change(screen.getByPlaceholderText('Repeat it'), { target: { value: confirm } });
}

describe('Change password — current-password re-auth (SCRUM-75)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('rejects a wrong current password with an inline error and never updates', async () => {
    verifyCurrentPassword.mockResolvedValue(false);
    render(<ChangePasswordPage />);
    fillForm({ current: 'wrongpass', next: 'newpassword123', confirm: 'newpassword123' });

    fireEvent.click(screen.getByRole('button', { name: 'Update password' }));

    await waitFor(() =>
      expect(verifyCurrentPassword).toHaveBeenCalledWith('me@example.com', 'wrongpass'),
    );
    expect(await screen.findByText('Current password is incorrect.')).toBeTruthy();
    expect(updatePassword).not.toHaveBeenCalled();
  });

  it('updates the password only after the current one verifies', async () => {
    verifyCurrentPassword.mockResolvedValue(true);
    updatePassword.mockResolvedValue(undefined);
    render(<ChangePasswordPage />);
    fillForm({ current: 'rightpass', next: 'newpassword123', confirm: 'newpassword123' });

    fireEvent.click(screen.getByRole('button', { name: 'Update password' }));

    await waitFor(() => expect(updatePassword).toHaveBeenCalledWith('newpassword123'));
    expect(await screen.findByText('Password updated ✓')).toBeTruthy();
  });

  it('locks the form after repeated wrong attempts (rate limit)', async () => {
    verifyCurrentPassword.mockResolvedValue(false);
    render(<ChangePasswordPage />);
    fillForm({ current: 'wrongpass', next: 'newpassword123', confirm: 'newpassword123' });

    const btn = screen.getByRole('button', { name: 'Update password' });
    for (let i = 0; i < 5; i++) {
      fireEvent.click(btn);
      await waitFor(() => expect(verifyCurrentPassword).toHaveBeenCalledTimes(i + 1));
    }
    // 5th failure trips the lockout: the button relabels + disables, so a 6th attempt
    // never reaches verifyCurrentPassword again.
    const locked = await screen.findByRole('button', { name: /Try again in \d+s/ });
    expect((locked as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(locked);
    expect(verifyCurrentPassword).toHaveBeenCalledTimes(5);
    expect(updatePassword).not.toHaveBeenCalled();
  });
});
