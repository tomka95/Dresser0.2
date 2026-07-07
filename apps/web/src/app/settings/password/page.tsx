'use client';

/**
 * /settings/password — change password.
 *
 * WIRED (real): Supabase auth.updateUser sets the new password on the active
 * session (updatePassword).
 *
 * HONEST: Supabase does NOT verify the current password client-side. Rather than
 * imply a check we can't do, the "current password" field is kept for muscle
 * memory but labeled — it is not verified here.
 */

import { useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import { CircleAlert, Key, Lock } from 'lucide-react';
import { useRequireAuth } from '@/lib/auth/useRequireAuth';
import { updatePassword } from '@/lib/auth';
import { AppShell } from '@/components/layout/AppShell';
import { Btn, Field, TopBar } from '@/components/ds';

function passwordStrength(pw: string): number {
  let score = 0;
  if (pw.length >= 8) score++;
  if (pw.length >= 12) score++;
  if (/[a-z]/.test(pw) && /[A-Z]/.test(pw)) score++;
  if (/[\d\W]/.test(pw)) score++;
  return pw.length === 0 ? 0 : Math.max(1, score);
}

const STRENGTH_LABEL = ['', 'Too weak', 'Fair', 'Good', 'Strong'];

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
  const tooShort = next.length > 0 && next.length < 8;

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
      <div style={{ padding: '62px 20px 40px' }}>
        <TopBar title="Change password" />
        <div className="h-[18px]" />

        <div className="flex flex-col" style={{ gap: 14 }}>
          <div>
            <Field
              label="Current password"
              type="password"
              value={current}
              onChange={setCurrent}
              placeholder="••••••••"
              icon={<Lock size={16} />}
            />
            <div className="mt-1.5 text-[11.5px] leading-snug text-white/[0.36]">
              For your reference only — it isn&rsquo;t verified here.
            </div>
          </div>

          <div>
            <Field
              label="New password"
              type="password"
              value={next}
              onChange={setNext}
              placeholder="••••••••••"
              icon={<Key size={16} />}
              error={tooShort}
            />
            {tooShort && (
              <div className="mt-1.5 flex items-center gap-1.5 text-[12px]" style={{ color: '#ff9096' }}>
                <CircleAlert size={13} /> Too short — 8 characters minimum.
              </div>
            )}
          </div>

          <Field
            label="Confirm new password"
            type="password"
            value={confirm}
            onChange={setConfirm}
            placeholder="Repeat it"
            icon={<Key size={16} />}
          />
        </div>

        {/* Strength meter — 4 segments. */}
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
          {next.length === 0 ? 'Use 12+ chars, mixed case, and a number' : STRENGTH_LABEL[strength]}
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

        <Btn
          variant="primary"
          fullWidth
          size="lg"
          className="mt-6"
          pending={busy}
          disabled={busy || !next || !confirm}
          onClick={handleSubmit}
        >
          Update password
        </Btn>
        <div className="mt-3 text-center text-[11.5px]" style={{ color: 'rgba(255,255,255,0.36)' }}>
          You&rsquo;ll stay signed in on this phone.
        </div>
      </div>
    </AppShell>
  );
}
