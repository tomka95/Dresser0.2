'use client';

/**
 * §6 · F7 — Saved / wishlist (ROADMAP, preview only).
 *
 * A grid of saved products with price-drop badges. HONEST: there is NO wishlist
 * backend — saves are DEVICE-ONLY bookmarks and the price-drop badges are mock,
 * not live tracking. The screen renders from SAVED_MOCK and labels itself clearly
 * so it never implies a synced wishlist or real price watching.
 */

import { useRouter } from 'next/navigation';
import { useRequireAuth } from '@/lib/auth/useRequireAuth';
import { AppShell } from '@/components/layout/AppShell';
import { BottomNavBar } from '@/components/layout/BottomNavBar';
import { ItemTile, M, NAV_CLEAR } from '@/components/ds';
import { SAVED_MOCK } from '@/lib/mock/shop';

export default function SavedPage() {
  const router = useRouter();
  const { session, loading } = useRequireAuth('/sign-in', { requireOnboarded: true });
  const isAuth = !!session;

  if (loading || !isAuth) return null;

  return (
    <AppShell>
      <div style={{ padding: `52px 20px ${NAV_CLEAR}px` }}>
        <div className="flex items-center gap-2">
          <h1 className="m-0 text-[30px] font-bold tracking-[-0.8px] text-white">Saved</h1>
          <span
            className="rounded-full uppercase"
            style={{
              padding: '3px 9px',
              fontSize: 9.5,
              fontWeight: 700,
              letterSpacing: '0.08em',
              color: 'var(--mint)',
              background: 'rgba(75,226,214,0.14)',
              border: '1px solid rgba(75,226,214,0.4)',
            }}
          >
            Preview
          </span>
        </div>
        <div className="mt-1 text-[13.5px]" style={{ color: M.faint }}>
          {SAVED_MOCK.length} pieces · saved on this device
        </div>

        <div className="mt-5 grid grid-cols-2 gap-3">
          {SAVED_MOCK.map((p) => (
            <ItemTile
              key={p.id}
              name={p.name}
              brand={p.brand}
              imageUrl={p.img}
              faved
              onClick={() => router.push(`/shop/${p.id}`)}
              badge={
                p.priceDrop ? (
                  <span
                    className="rounded-full font-bold"
                    style={{
                      padding: '4px 9px',
                      background: 'rgba(75,226,214,0.92)',
                      color: '#06302d',
                      fontSize: 10,
                    }}
                  >
                    ↓ {p.priceDrop.pct}% · ${p.price}
                  </span>
                ) : (
                  <span
                    className="rounded-full font-bold"
                    style={{
                      padding: '4px 9px',
                      background: 'rgba(0,0,0,0.5)',
                      backdropFilter: 'blur(8px)',
                      WebkitBackdropFilter: 'blur(8px)',
                      border: '1px solid rgba(255,255,255,0.18)',
                      color: '#fff',
                      fontSize: 10,
                    }}
                  >
                    ${p.price}
                  </span>
                )
              }
            />
          ))}
        </div>

        <div className="mt-6 text-center text-[11px]" style={{ color: M.ghost }}>
          Price-drop watching is a preview — bookmarks live only on this device for now.
        </div>
      </div>

      <BottomNavBar activeRoute="/saved" />
    </AppShell>
  );
}
