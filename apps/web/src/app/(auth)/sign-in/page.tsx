'use client';

import React, { useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { Mail, Lock } from 'lucide-react';

import { signInWithPassword, signInWithProvider } from '@/lib/auth';
import { enabledProviders } from '@/config/authProviders';
import { LightButton } from '@/components/ui/LightButton';
import {
  AuthLogo,
  AuthCard,
  GlassInput,
  OrDivider,
  ProviderButton,
  GoogleG,
  AppleA,
} from '@/components/auth/AuthUI';

export default function SignInPage() {
  const router = useRouter();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const appleEnabled = enabledProviders().some((p) => p.id === 'apple');

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      await signInWithPassword({ email, password });
      router.push('/home');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Something went wrong.');
      setLoading(false);
    }
  }

  async function handleProvider(id: 'google' | 'apple') {
    setError(null);
    try {
      await signInWithProvider(id);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Something went wrong.');
    }
  }

  return (
    <>
      <AuthLogo />
      <AuthCard>
        <h1 style={{ fontSize: 24, fontWeight: 700, color: '#fff', margin: 0 }}>
          Welcome back
        </h1>
        <p style={{ color: 'rgba(255,255,255,0.6)', margin: '6px 0 20px', fontSize: 15 }}>
          Sign in to your closet
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
          <GlassInput
            icon={<Lock size={18} />}
            type="password"
            placeholder="Password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />

          <div style={{ textAlign: 'right' }}>
            <Link
              href="/forgot-password"
              style={{ color: 'rgba(255,255,255,0.7)', fontSize: 13 }}
            >
              Forgot password?
            </Link>
          </div>

          {error ? (
            <p style={{ color: 'var(--danger)', fontSize: 13, margin: 0 }}>{error}</p>
          ) : null}

          <LightButton type="submit" fullWidth disabled={loading}>
            {loading ? 'Signing in…' : 'Sign in'}
          </LightButton>
        </form>

        <OrDivider />

        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <ProviderButton icon={<GoogleG />} onClick={() => handleProvider('google')}>
            Continue with Google
          </ProviderButton>
          {appleEnabled ? (
            <ProviderButton icon={<AppleA />} onClick={() => handleProvider('apple')}>
              Continue with Apple
            </ProviderButton>
          ) : null}
        </div>

        <p
          style={{
            textAlign: 'center',
            color: 'rgba(255,255,255,0.6)',
            fontSize: 14,
            margin: '20px 0 0',
          }}
        >
          New here?{' '}
          <Link href="/sign-up" style={{ color: '#fff', fontWeight: 600 }}>
            Create account
          </Link>
        </p>
      </AuthCard>
    </>
  );
}
