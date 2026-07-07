'use client';

/**
 * /creator/[handle] — §6 · F9 Creator closet (ROADMAP preview, fully MOCK).
 *
 * Browse + "shop" a creator's public closet. There is NO creators backend, so the
 * entire screen is mock (CREATOR_MOCK profile + SHOP_PRODUCTS grid) and clearly
 * labeled a "preview". The [handle] param is display-only — it does not resolve a
 * real creator.
 *
 * MONETIZATION BOUNDARY: the mock products carry no real productId. A tap opens
 * the product detail (/shop/[id]), where the buy CTA already honest-disables
 * itself for mock ids ("Shopping links coming soon"). This page NEVER constructs
 * a destination / affiliate URL and never mints a click — there is nothing real
 * to open. useRequireAuth guards.
 */

import { useRouter } from 'next/navigation';
import { useRequireAuth } from '@/lib/auth/useRequireAuth';
import { CREATOR_MOCK, SHOP_PRODUCTS } from '@/lib/mock/shop';
import { AppShell } from '@/components/layout/AppShell';
import { Btn, TopBar, ItemTile, M, NAV_CLEAR } from '@/components/ds';

const FILTERS = ['All', 'Shoppable', 'Most worn'] as const;

export default function CreatorClosetPage({
  params,
}: {
  params: { handle: string };
}) {
  const router = useRouter();
  const { session, loading } = useRequireAuth();
  const isAuth = !!session;

  if (loading || !isAuth) return null;

  const C = CREATOR_MOCK;
  // Display the requested handle when present, else fall back to the mock's.
  const handle = params.handle ? `@${params.handle.replace(/^@/, '')}` : C.handle;

  return (
    <AppShell>
      <div style={{ padding: `52px 20px ${NAV_CLEAR}px` }}>
        <TopBar title="Creator closet" />

        {/* Preview banner — the entire creator surface is a roadmap preview. */}
        <div
          className="mt-3.5 flex items-center gap-2 rounded-full"
          style={{
            width: 'fit-content',
            padding: '5px 12px',
            background: 'rgba(150,120,230,0.16)',
            border: '1px solid rgba(150,120,230,0.4)',
            color: '#c9bcf5',
            fontSize: 11,
            fontWeight: 650,
          }}
        >
          Preview · creator closets are coming soon
        </div>

        {/* Creator header (MOCK). */}
        <div className="mt-4 flex items-center gap-3.5" style={{ ...M.glass(26), padding: 18 }}>
          <span
            className="flex shrink-0 items-center justify-center rounded-full text-white"
            style={{
              width: 62,
              height: 62,
              background: 'linear-gradient(165deg, #147f74, #0a3633)',
              border: '1px solid rgba(255,255,255,0.2)',
              fontSize: 21,
              fontWeight: 700,
            }}
            aria-hidden
          >
            {C.initials}
          </span>
          <div className="min-w-0 flex-1">
            <div className="text-[17px] font-bold tracking-[-0.3px] text-white">{C.name}</div>
            <div style={{ color: M.faint, fontSize: 12, marginTop: 2 }}>
              {handle} · {C.followers} followers
            </div>
            <div style={{ color: M.faint, fontSize: 11.5, marginTop: 4 }}>
              {C.pieces} pieces · {C.shoppable} shoppable
            </div>
          </div>
          <Btn
            variant="glass"
            size="sm"
            disabled
            title="Following creators is coming soon"
          >
            Follow
          </Btn>
        </div>

        {/* Filter chips — decorative in the preview (no real filtering to do). */}
        <div className="mb-3 mt-3.5 flex gap-2">
          {FILTERS.map((c, i) => (
            <span
              key={c}
              className="rounded-full text-[12.5px] font-semibold"
              style={{
                padding: '7px 14px',
                background: i === 1 ? 'var(--mint)' : 'rgba(255,255,255,0.06)',
                color: i === 1 ? 'var(--brand-teal)' : 'rgba(255,255,255,0.75)',
                border: i === 1 ? 'none' : '1px solid rgba(255,255,255,0.12)',
              }}
            >
              {c}
            </span>
          ))}
        </div>

        {/* Shoppable grid (MOCK). Tapping opens /shop/[id], which honest-disables
            the buy CTA for these mock ids — no client-side URL is ever built. */}
        <div className="grid grid-cols-2 gap-3">
          {SHOP_PRODUCTS.map((p) => (
            <ItemTile
              key={p.id}
              name={p.name}
              brand={p.brand}
              imageUrl={p.img}
              onClick={() => router.push(`/shop/${p.id}`)}
              badge={
                <span
                  className="rounded-full font-bold"
                  style={{
                    padding: '4px 9px',
                    background: 'rgba(75,226,214,0.9)',
                    color: '#06302d',
                    fontSize: 10,
                  }}
                >
                  SHOP · ${p.price}
                </span>
              }
            />
          ))}
        </div>

        <div className="mt-3.5 text-center text-[11px]" style={{ color: M.ghost }}>
          Preview only · {C.name} isn’t a real creator yet
        </div>
      </div>
    </AppShell>
  );
}
