'use client';

/**
 * /shop/[id] — shoppable product detail (destination of search/outfit shop tiles).
 * FRONTEND-ONLY: renders the mock catalog; no shop backend yet. The recommended
 * size line reads the locally-saved sizes when present.
 */

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { Bookmark, Heart } from 'lucide-react';
import { useRequireAuth } from '@/lib/auth/useRequireAuth';
import { AppShell } from '@/components/layout/AppShell';
import { ItemImage } from '@/components/ui/ItemImage';
import { DSButton, TopBar } from '@/components/ds';
import { getShopProduct } from '@/lib/mock/shop';

interface ShopDetailPageProps {
  params: { id: string };
}

export default function ShopDetailPage({ params }: ShopDetailPageProps) {
  const router = useRouter();
  const { session, loading } = useRequireAuth();
  const product = getShopProduct(params.id);

  const [size, setSize] = useState<string | null>(null);
  const [savedNote, setSavedNote] = useState<string | null>(null);
  const [faved, setFaved] = useState(false);

  useEffect(() => {
    if (product) setSize(product.recommendedSize);
  }, [product]);

  if (loading || !session) return null;

  if (!product) {
    return (
      <AppShell scroll={false}>
        <div className="flex h-full flex-col items-center justify-center px-8 text-center">
          <h1 className="m-0 text-[20px] font-bold text-white">Product not found</h1>
          <p className="mb-6 mt-2 text-sm text-white/60">This suggestion is no longer available.</p>
          <DSButton variant="light" pill onClick={() => router.push('/search')} style={{ height: 48, padding: '0 26px' }}>
            Back to search
          </DSButton>
        </div>
      </AppShell>
    );
  }

  return (
    <AppShell>
      {/* Hero */}
      <div className="relative" style={{ height: 380 }}>
        <ItemImage src={product.img} alt={product.name} fit="cover" />
        <div
          className="pointer-events-none absolute inset-0"
          style={{ background: 'linear-gradient(180deg, rgba(0,0,0,0.4) 0%, transparent 30%, rgba(30,30,30,0.96) 100%)' }}
          aria-hidden
        />
        <div className="absolute left-4 right-4" style={{ top: 48 }}>
          <TopBar
            right={
              <button
                type="button"
                aria-label={faved ? 'Unfavorite' : 'Favorite'}
                onClick={() => setFaved((f) => !f)}
                className="flex h-10 w-10 items-center justify-center"
                style={{ color: faved ? 'var(--mint)' : '#fff' }}
              >
                <Heart size={20} fill={faved ? 'currentColor' : 'none'} />
              </button>
            }
          />
        </div>
        <span
          className="absolute rounded-full font-bold"
          style={{
            top: 92,
            left: 24,
            fontSize: 10.5,
            letterSpacing: '0.4px',
            color: 'var(--brand-teal)',
            background: 'var(--mint)',
            padding: '4px 10px',
          }}
        >
          SHOP
        </span>
      </div>

      <div className="relative" style={{ padding: '0 24px 140px', marginTop: -34 }}>
        <div
          className="font-accent uppercase"
          style={{ color: 'rgba(255,255,255,0.6)', fontSize: 13, letterSpacing: '0.5px' }}
        >
          {product.brand}
        </div>
        <div className="mt-1 flex items-baseline justify-between gap-3">
          <h1 className="m-0 text-[26px] font-bold tracking-[-0.4px] text-white">{product.name}</h1>
          <div className="text-[22px] font-bold text-white">${product.price}</div>
        </div>

        {/* AI rationale */}
        <div
          className="my-[18px] flex items-start gap-2.5 rounded-[14px]"
          style={{ padding: '13px 14px', background: 'var(--grad-ai)', border: '1px solid var(--tr-20)' }}
        >
          <span className="mt-px" style={{ color: 'var(--mint)' }}>✦</span>
          <span className="text-[13.5px] leading-snug text-white/[0.88]">{product.reason}</span>
        </div>

        <div
          className="mx-0.5 mb-2.5 text-[12.5px] font-semibold"
          style={{ color: 'rgba(255,255,255,0.6)', letterSpacing: '0.3px' }}
        >
          SELECT SIZE
        </div>
        <div className="flex gap-2.5">
          {product.sizes.map((s) => {
            const on = size === s;
            return (
              <button
                key={s}
                type="button"
                onClick={() => setSize(s)}
                className="flex-1 rounded-xl py-[13px] text-center text-[14.5px] font-semibold transition-colors"
                style={{
                  color: on ? 'var(--brand-teal)' : '#fff',
                  background: on ? 'var(--mint)' : 'var(--tr-10)',
                  border: `1px solid ${on ? 'transparent' : 'var(--tr-20)'}`,
                }}
              >
                {s}
              </button>
            );
          })}
        </div>
        {size === product.recommendedSize && (
          <div className="mx-0.5 mt-3 flex items-center gap-1.5 text-[12.5px]" style={{ color: 'var(--mint)' }}>
            <span className="rounded-full" style={{ width: 7, height: 7, background: 'var(--mint)' }} aria-hidden />
            Size {product.recommendedSize} matches your saved fit
          </div>
        )}

        {savedNote && (
          <p className="mt-4 rounded-xl px-3 py-2 text-center text-[12.5px]" style={{ background: 'var(--tr-10)', color: 'rgba(255,255,255,0.75)' }}>
            {savedNote}
          </p>
        )}
      </div>

      {/* Bottom actions */}
      <div
        className="fixed bottom-0 left-0 right-0 z-40 mx-auto flex max-w-[430px] gap-3"
        style={{ padding: '16px 24px 26px', background: 'linear-gradient(to top, rgba(30,30,30,0.98), transparent)' }}
      >
        <button
          type="button"
          aria-label="Save for later"
          onClick={() => {
            setSavedNote('Saved for later — a wishlist backend is coming soon.');
            setTimeout(() => setSavedNote(null), 2500);
          }}
          className="flex shrink-0 items-center justify-center rounded-full"
          style={{
            width: 54,
            height: 50,
            border: '1px solid var(--tr-20)',
            background: 'rgba(0,0,0,0.3)',
            color: 'var(--mint)',
          }}
        >
          <Bookmark size={20} />
        </button>
        <DSButton
          variant="light"
          pill
          className="flex-1"
          onClick={() =>
            window.open(
              `https://www.google.com/search?q=${encodeURIComponent(`${product.brand} ${product.name}`)}`,
              '_blank',
              'noopener'
            )
          }
        >
          Shop at {product.brand}
        </DSButton>
      </div>
    </AppShell>
  );
}
