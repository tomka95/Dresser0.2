'use client';

import React, { useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { User, Mail, Lock } from 'lucide-react';

import { signUpWithPassword, signInWithProvider } from '@/lib/auth';
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

export default function SignUpPage() {
  const router = useRouter();
  const [fullName, setFullName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sent, setSent] = useState(false);

  const appleEnabled = enabledProviders().some((p) => p.id === 'apple');

  async function submitSignUp() {
    setError(null);
    setLoading(true);
    try {
      const { needsEmailConfirmation } = await signUpWithPassword({
        email,
        password,
        fullName,
      });
      if (needsEmailConfirmation) {
        setSent(true);
        setLoading(false);
      } else {
        router.push('/home');
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Something went wrong.');
      setLoading(false);
    }
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    await submitSignUp();
  }

  async function handleProvider(id: 'google' | 'apple') {
    setError(null);
    try {
      await signInWithProvider(id);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Something went wrong.');
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
            <Mail size={26} style={{ color: 'var(--mint)' }} />
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
            Check your email
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
            We sent a confirmation link to{' '}
            <span style={{ color: '#fff', fontWeight: 600 }}>{email}</span>. Tap it to finish
            setting up.
          </p>

          {error ? (
            <p
              style={{
                color: 'var(--danger)',
                fontSize: 13,
                margin: '0 0 12px',
                textAlign: 'center',
              }}
            >
              {error}
            </p>
          ) : null}

          <LightButton fullWidth onClick={() => (window.location.href = 'mailto:')}>
            Open email app
          </LightButton>

          <p
            style={{
              textAlign: 'center',
              color: 'rgba(255,255,255,0.6)',
              fontSize: 14,
              margin: '20px 0 0',
            }}
          >
            Didn&rsquo;t get it?{' '}
            <button
              type="button"
              onClick={submitSignUp}
              disabled={loading}
              style={{
                background: 'none',
                border: 'none',
                padding: 0,
                color: '#fff',
                fontWeight: 600,
                fontSize: 14,
                cursor: 'pointer',
              }}
            >
              {loading ? 'Resending…' : 'Resend'}
            </button>
          </p>
        </AuthCard>
      </>
    );
  }

  return (
    <>
      <AuthLogo />
      <AuthCard>
        <h1 style={{ fontSize: 24, fontWeight: 700, color: '#fff', margin: 0 }}>
          Create account
        </h1>
        <p style={{ color: 'rgba(255,255,255,0.6)', margin: '6px 0 20px', fontSize: 15 }}>
          Sign up to get started
        </p>

        <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <GlassInput
            icon={<User size={18} />}
            type="text"
            placeholder="Full name"
            autoComplete="name"
            value={fullName}
            onChange={(e) => setFullName(e.target.value)}
          />
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
            autoComplete="new-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />

          {error ? (
            <p style={{ color: 'var(--danger)', fontSize: 13, margin: 0 }}>{error}</p>
          ) : null}

          <LightButton type="submit" fullWidth disabled={loading}>
            {loading ? 'Signing up…' : 'Sign up'}
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
          Already have an account?{' '}
          <Link href="/sign-in" style={{ color: '#fff', fontWeight: 600 }}>
            Sign in
          </Link>
        </p>
      </AuthCard>
    </>
  );
}
