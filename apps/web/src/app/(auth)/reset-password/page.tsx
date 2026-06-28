'use client';

import React, { useState } from 'react';
import { useRouter } from 'next/navigation';
import { Lock } from 'lucide-react';

import { updatePassword } from '@/lib/auth';
import { LightButton } from '@/components/ui/LightButton';
import { AuthLogo, AuthCard, GlassInput } from '@/components/auth/AuthUI';

function passwordScore(pw: string): number {
  let score = 0;
  if (pw.length >= 8) score += 1;
  if (/[0-9]/.test(pw)) score += 1;
  if (/[^A-Za-z0-9]/.test(pw)) score += 1;
  return score;
}

export default function ResetPasswordPage() {
  const router = useRouter();
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const score = passwordScore(password);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);

    if (password !== confirm) {
      setError('Passwords do not match.');
      return;
    }

    setLoading(true);
    try {
      await updatePassword(password);
      router.push('/sign-in');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Something went wrong.');
      setLoading(false);
    }
  }

  return (
    <>
      <AuthLogo />
      <AuthCard>
        <h1 style={{ fontSize: 24, fontWeight: 700, color: '#fff', margin: 0 }}>
          Set new password
        </h1>
        <p
          style={{
            color: 'rgba(255,255,255,0.6)',
            margin: '6px 0 20px',
            fontSize: 15,
            lineHeight: 1.5,
          }}
        >
          Choose a strong password you&rsquo;ll remember.
        </p>

        <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <GlassInput
            icon={<Lock size={18} />}
            type="password"
            placeholder="New password"
            autoComplete="new-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />

          {/* 3-segment strength meter */}
          <div style={{ display: 'flex', gap: 8 }}>
            {[0, 1, 2].map((i) => (
              <div
                key={i}
                style={{
                  flex: 1,
                  height: 4,
                  borderRadius: 999,
                  background: i < score ? 'var(--mint)' : 'var(--tr-20)',
                }}
              />
            ))}
          </div>

          <GlassInput
            icon={<Lock size={18} />}
            type="password"
            placeholder="Confirm password"
            autoComplete="new-password"
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            required
          />

          {error ? (
            <p style={{ color: 'var(--danger)', fontSize: 13, margin: 0 }}>{error}</p>
          ) : null}

          <LightButton type="submit" fullWidth disabled={loading}>
            {loading ? 'Updating…' : 'Update password'}
          </LightButton>
        </form>
      </AuthCard>
    </>
  );
}
