'use client';

import React, { useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { Mail, RotateCw } from 'lucide-react';

import { requestPasswordReset } from '@/lib/auth';
import { LightButton } from '@/components/ui/LightButton';
import { AuthLogo, AuthCard, GlassInput } from '@/components/auth/AuthUI';

export default function ForgotPasswordPage() {
  const router = useRouter();
  const [email, setEmail] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sent, setSent] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      await requestPasswordReset(email);
      setSent(true);
      setLoading(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Something went wrong.');
      setLoading(false);
    }
  }

  if (sent) {
    return (
      <>
        <AuthLogo />
        <AuthCard>
          <div
            style={{
              width: 56,
              height: 56,
              borderRadius: 999,
              background: 'rgba(75,226,214,0.16)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              margin: '0 auto 16px',
            }}
          >
            <RotateCw size={26} style={{ color: 'var(--mint)' }} />
          </div>
          <h1
            style={{
              fontSize: 24,
              fontWeight: 700,
              color: '#fff',
              margin: 0,
              textAlign: 'center',
            }}
          >
            Link sent
          </h1>
          <p
            style={{
              color: 'rgba(255,255,255,0.7)',
              margin: '10px 0 20px',
              fontSize: 15,
              textAlign: 'center',
              lineHeight: 1.5,
            }}
          >
            Check <span style={{ color: '#fff', fontWeight: 600 }}>{email}</span> for a reset
            link. It expires in 30 minutes.
          </p>
          <LightButton fullWidth onClick={() => router.push('/sign-in')}>
            Back to sign in
          </LightButton>
        </AuthCard>
      </>
    );
  }

  return (
    <>
      <AuthLogo />
      <AuthCard>
        <h1 style={{ fontSize: 24, fontWeight: 700, color: '#fff', margin: 0 }}>
          Reset password
        </h1>
        <p
          style={{
            color: 'rgba(255,255,255,0.6)',
            margin: '6px 0 20px',
            fontSize: 15,
            lineHeight: 1.5,
          }}
        >
          Enter your email and we&rsquo;ll send you a link to set a new password.
        </p>

        <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <GlassInput
            icon={<Mail size={18} />}
            type="email"
            placeholder="Email"
            autoComplete="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
          />

          {error ? (
            <p style={{ color: 'var(--danger)', fontSize: 13, margin: 0 }}>{error}</p>
          ) : null}

          <LightButton type="submit" fullWidth disabled={loading}>
            {loading ? 'Sending…' : 'Send reset link'}
          </LightButton>
        </form>

        <p
          style={{
            textAlign: 'center',
            color: 'rgba(255,255,255,0.7)',
            fontSize: 14,
            margin: '20px 0 0',
          }}
        >
          <Link href="/sign-in" style={{ color: 'rgba(255,255,255,0.7)' }}>
            &larr; Back to sign in
          </Link>
        </p>
      </AuthCard>
    </>
  );
}
