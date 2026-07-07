'use client';

/**
 * §6 · F6 — Rate-a-look (ROADMAP, preview only).
 *
 * A swipe deck that would "tune the shop ranker". HONEST: there is NO rate-a-look
 * backend — swipe actions are local no-ops with a "preview" label. The deck renders
 * from the mock catalog so the interaction can be previewed; nothing is persisted
 * and no ranker is affected.
 */

import { useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import { Heart, X } from 'lucide-react';
import { useRequireAuth } from '@/lib/auth/useRequireAuth';
import { AppShell } from '@/components/layout/AppShell';
import { ItemImage } from '@/components/ui/ItemImage';
import { RoundBtn, TopBar, M } from '@/components/ds';
import { SHOP_PRODUCTS } from '@/lib/mock/shop';

export default function RateALookPage() {
  const router = useRouter();
  const { session, loading } = useRequireAuth('/sign-in', { requireOnboarded: true });
  const isAuth = !!session;

  const deck = useMemo(() => SHOP_PRODUCTS, []);
  const [index, setIndex] = useState(0);

  if (loading || !isAuth) return null;

  const total = deck.length;
  const current = deck[index] ?? null;
  const next = () => setIndex((i) => Math.min(i + 1, total));

  return (
    <AppShell scroll={false}>
      <TopBar
        title="Rate looks"
        sub="Tunes your shop feed · preview"
        right={
          <span style={{ color: M.faint, fontSize: 12.5 }}>
            {Math.min(index + 1, total)} of {total}
          </span>
        }
      />

      <div className="absolute" style={{ inset: '128px 30px 190px' }}>
        {/* Back card peeking */}
        {current && (
          <div
            className="absolute"
            style={{
              inset: '14px 8px -8px',
              borderRadius: 28,
              background: 'rgba(255,255,255,0.05)',
              border: '1px solid rgba(255,255,255,0.08)',
              transform: 'rotate(3deg)',
            }}
            aria-hidden
          />
        )}
        {current ? (
          <div className="absolute inset-0 overflow-hidden" style={{ ...M.deep(28) }}>
            <ItemImage src={current.img} alt={current.name} fit="cover" />
            <div
              className="pointer-events-none absolute inset-0"
              style={{ background: 'linear-gradient(to top, rgba(0,0,0,0.78) 0%, transparent 55%)' }}
              aria-hidden
            />
            <div className="absolute" style={{ left: 18, right: 18, bottom: 18 }}>
              <div className="text-[18px] font-bold tracking-[-0.3px] text-white">{current.name}</div>
              <div style={{ color: 'rgba(255,255,255,0.7)', fontSize: 12 }}>
                {current.brand} · ${current.price}
              </div>
            </div>
          </div>
        ) : (
          <div
            className="absolute inset-0 flex flex-col items-center justify-center text-center"
            style={{ ...M.deep(28), padding: 24 }}
          >
            <div className="text-[17px] font-bold text-white">That’s the deck</div>
            <div className="mt-2 text-[13px]" style={{ color: M.faint }}>
              In the shipped version, these ratings would tune your shop feed.
            </div>
            <button
              type="button"
              onClick={() => router.push('/home')}
              className="mt-5 text-[13px] font-semibold"
              style={{ color: 'var(--mint)' }}
            >
              Back to Home
            </button>
          </div>
        )}
      </div>

      {current && (
        <>
          <div
            className="absolute flex justify-center"
            style={{ left: 0, right: 0, bottom: 98, gap: 22 }}
          >
            <RoundBtn size={58} aria-label="Skip this look" icon={<X size={24} />} onClick={next} />
            <button
              type="button"
              aria-label="Like this look"
              onClick={next}
              className="flex items-center justify-center rounded-full"
              style={{
                width: 58,
                height: 58,
                background: 'linear-gradient(165deg, #52e8dc, #2cc9bc)',
                border: '1px solid rgba(255,255,255,0.3)',
                boxShadow: '0 12px 30px -8px rgba(75,226,214,0.5)',
                color: '#06302d',
              }}
            >
              <Heart size={24} />
            </button>
          </div>
          <div
            className="absolute text-center"
            style={{ left: 0, right: 0, bottom: 40, color: M.ghost, fontSize: 11.5 }}
          >
            Preview — ratings aren’t saved yet
          </div>
        </>
      )}
    </AppShell>
  );
}
