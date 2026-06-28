'use client';

import { useRouter } from 'next/navigation';
import { Shirt } from 'lucide-react';

import { AppShell } from '@/components/layout/AppShell';
import { LightButton } from '@/components/ui/LightButton';

export default function NotFound() {
  const router = useRouter();

  return (
    <AppShell scroll={false}>
      <div className="flex h-full flex-col items-center justify-center px-8 text-center">
        <div
          className="font-bold leading-none text-white"
          style={{ fontSize: 96, fontWeight: 800, letterSpacing: '-2px' }}
        >
          404
        </div>

        <div
          className="my-6 flex items-center justify-center"
          style={{
            width: 72,
            height: 72,
            borderRadius: '50%',
            background: 'var(--tr-10)',
            border: '1px solid var(--tr-20)',
          }}
        >
          <Shirt size={32} color="var(--mint)" />
        </div>

        <h1 className="m-0 text-[22px] font-bold text-white">This rack is empty</h1>
        <p
          className="mx-auto mt-2.5 mb-7 text-[14.5px] leading-relaxed"
          style={{ color: 'rgba(255,255,255,0.65)', maxWidth: 280 }}
        >
          The page you&rsquo;re looking for doesn&rsquo;t exist or has moved.
        </p>

        <LightButton onClick={() => router.push('/home')} style={{ height: 48, padding: '0 26px' }}>
          Back to home
        </LightButton>
      </div>
    </AppShell>
  );
}
