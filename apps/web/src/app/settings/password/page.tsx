'use client';

/**
 * /settings/password — change password. REAL: Supabase auth.updateUser sets the
 * new password on the active session. (Supabase doesn't verify the current
 * password client-side; the field is kept for the designed flow.)
 */

import { useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import { useRequireAuth } from '@/lib/auth/useRequireAuth';
import { updatePassword } from '@/lib/auth';
import { AppShell } from '@/components/layout/AppShell';
import { DSButton, FormField, TopBar } from '@/components/ds';

function passwordStrength(pw: string): number {
  let score = 0;
  if (pw.length >= 8) score++;
  if (pw.length >= 12) score++;
  if (/[a-z]/.test(pw) && /[A-Z]/.test(pw)) score++;
  if (/[\d\W]/.test(pw)) score++;
  return pw.length === 0 ? 0 : Math.max(1, score);
}

export default function ChangePasswordPage() {
  const router = useRouter();
  const { session, loading } = useRequireAuth();

  const [current, setCurrent] = useState('');
  const [next, setNext] = useState('');
  const [confirm, setConfirm] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  const strength = useMemo(() => passwordStrength(next), [next]);

  if (loading || !session) return null;

  const handleSubmit = async () => {
    setError(null);
    if (next.length < 8) {
      setError('New password must be at least 8 characters.');
      return;
    }
    if (next !== confirm) {
      setError("New passwords don't match.");
      return;
    }
    setBusy(true);
    try {
      await updatePassword(next);
      setDone(true);
      setTimeout(() => router.push('/settings'), 900);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't update the password.");
      setBusy(false);
    }
  };

  return (
    <AppShell>
      <div className="flex min-h-full flex-col" style={{ padding: '48px 24px 40px' }}>
        <TopBar title="Change password" />
        <div className="h-[18px]" />
        <p className="m-0 mb-5 text-[14.5px] leading-relaxed text-white/70">
          Enter your current password, then choose a new one.
        </p>

        <div className="flex flex-col gap-4">
          <FormField label="Current password" type="password" value={current} onChange={setCurrent} placeholder="••••••••" />
          <FormField label="New password" type="password" value={next} onChange={setNext} placeholder="••••••••••" />
          <FormField label="Confirm new password" type="password" value={confirm} onChange={setConfirm} placeholder="••••••••••" />
        </div>

        {/* Strength meter — 4 segments */}
        <div className="mx-0.5 mt-4 flex gap-2" aria-hidden>
          {[1, 2, 3, 4].map((seg) => (
            <div
              key={seg}
              className="h-1 flex-1 rounded-sm transition-colors"
              style={{ background: strength >= seg ? 'var(--mint)' : 'var(--tr-20)' }}
            />
          ))}
        </div>
        <div className="mx-0.5 mt-2 text-[12.5px]" style={{ color: 'rgba(255,255,255,0.5)' }}>
          Strong — 12+ chars, mixed case, a number
        </div>

        {error && (
          <p className="mt-4 rounded-lg border border-red-500/50 bg-red-500/10 p-3 text-center text-sm text-red-400">
            {error}
          </p>
        )}
        {done && (
          <p className="mt-4 text-center text-sm" style={{ color: 'var(--success)' }}>
            Password updated ✓
          </p>
        )}

        <div className="flex-1" />
        <DSButton
          variant="light"
          fullWidth
          pill
          className="mt-6"
          loading={busy}
          disabled={busy || !next || !confirm}
          onClick={handleSubmit}
        >
          {busy ? 'Updating…' : 'Update password'}
        </DSButton>
      </div>
    </AppShell>
  );
}
