'use client';

import React, { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';

import { getSessionUser } from '@/lib/auth';
import { LightButton } from '@/components/ui/LightButton';
import { AuthLogo } from '@/components/auth/AuthUI';

function firstNameOf(name: string | undefined, email: string | undefined): string | null {
  if (name && name.trim()) return name.trim().split(/\s+/)[0];
  if (email && email.includes('@')) return email.split('@')[0];
  return null;
}

export default function EmailConfirmedPage() {
  const router = useRouter();
  const [firstName, setFirstName] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    getSessionUser()
      .then((user) => {
        if (cancelled) return;
        const name = user?.user_metadata?.full_name as string | undefined;
        setFirstName(firstNameOf(name, user?.email ?? undefined));
      })
      .catch(() => {
        /* fall back to the generic greeting */
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const greeting = firstName ? `You’re in, ${firstName}` : 'You’re in';

  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', textAlign: 'center' }}>
      <AuthLogo />

      <div
        style={{
          width: 72,
          height: 72,
          borderRadius: 999,
          background: 'rgba(75,226,214,0.18)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          margin: '8px 0 20px',
        }}
      >
        <svg
          width="34"
          height="34"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2.4"
          strokeLinecap="round"
          strokeLinejoin="round"
          style={{ color: 'var(--mint)' }}
        >
          <path d="M20 6L9 17l-5-5" />
        </svg>
      </div>

      <h1 style={{ fontSize: 24, fontWeight: 700, color: '#fff', margin: 0 }}>{greeting}</h1>
      <p
        style={{
          color: 'rgba(255,255,255,0.7)',
          margin: '10px 0 24px',
          fontSize: 15,
          lineHeight: 1.5,
          maxWidth: 320,
        }}
      >
        Your account is confirmed. Let&rsquo;s build your closet.
      </p>

      <div style={{ width: '100%' }}>
        <LightButton fullWidth onClick={() => router.push('/home')}>
          Get started
        </LightButton>
      </div>
    </div>
  );
}
