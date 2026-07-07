'use client';

/**
 * /shop/[id] — shoppable product detail.
 *
 * Resolution order for the product id:
 *   1. REAL: look the id up in the live /shop feed (a product card, or the
 *      buyable slot of an outfit card). When found, the buy CTA is the REAL
 *      monetized redirect → openProduct(productId, 'product_detail').
 *   2. MOCK: fall back to the mock catalog (lib/mock/shop) for DISPLAY only.
 *      The mock ids (s1–s4) are not real productIds, so the buy CTA is disabled
 *      honestly ("Shopping links coming soon") rather than faking a redirect.
 *
 * MONETIZATION: the buy CTA never builds a destination URL. It mints a click and
 * follows /out/{clickId} as a top-level navigation (openProduct). Bookmark/save
 * stays honest local ("Saved on this device").
 */

import { useEffect, useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { Bell, Bookmark, ExternalLink } from 'lucide-react';
import { useRequireAuth } from '@/lib/auth/useRequireAuth';
import { logEvent } from '@/lib/api/events';
import {
  getShopFeed,
  ShopAuthError,
  type Card,
  type ProductCard,
  type GoesWithItem,
} from '@/lib/api/shop';
import { AppShell } from '@/components/layout/AppShell';
import { ItemImage } from '@/components/ui/ItemImage';
import { Btn, DSButton, RoundBtn, Spark, Icon, TopBar, ItemTile, SkDetail, M, NAV_CLEAR } from '@/components/ds';
import { useAffiliateOpen } from '@/components/shop/useAffiliateOpen';
import { WhyThisRecSheet } from '@/components/profile/WhyThisRecSheet';
import { getShopProduct, SHOP_PRODUCTS, type ShopProduct } from '@/lib/mock/shop';

interface ShopDetailPageProps {
  params: { id: string };
}

/** Normalized display shape used by the view regardless of source. */
interface ResolvedProduct {
  /** Present ONLY for real backend products — gates the monetized CTA. */
  realProductId?: string;
  name: string;
  brand: string;
  price: number;
  imageUrl?: string | null;
  /** AI rationale line (real headline, or mock reason). */
  reason?: string;
  sizes?: string[];
  recommendedSize?: string;
  goesWith?: GoesWithItem[];
  unlockCount?: number;
}

function fromCard(card: ProductCard): ResolvedProduct {
  return {
    realProductId: card.product.productId,
    name: card.product.name,
    brand: card.product.brand,
    price: card.product.price,
    imageUrl: card.product.imageUrl,
    reason: card.headline,
    goesWith: card.goesWith,
    unlockCount: card.unlockCount,
  };
}

function fromMock(p: ShopProduct): ResolvedProduct {
  return {
    name: p.name,
    brand: p.brand,
    price: p.price,
    imageUrl: p.img,
    reason: p.reason,
    sizes: p.sizes,
    recommendedSize: p.recommendedSize,
  };
}

/** Find a matching product card in a feed page by productId. */
function findInCards(cards: Card[], id: string): ProductCard | null {
  for (const c of cards) {
    if (c.type === 'product' && c.product.productId === id) return c;
  }
  return null;
}

export default function ShopDetailPage({ params }: ShopDetailPageProps) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { session, loading } = useRequireAuth();

  // OOS is PRESENTATIONAL only — the feed carries no stock field. The design's
  // out-of-stock state (notify-me + in-stock alternatives) is reachable via
  // ?state=oos so the UI can be previewed honestly; it's never inferred from real
  // backend data because there is none to infer it from.
  const oos = searchParams.get('state') === 'oos';

  const [resolving, setResolving] = useState(true);
  const [product, setProduct] = useState<ResolvedProduct | null>(null);
  const [size, setSize] = useState<string | null>(null);
  const [savedNote, setSavedNote] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [notified, setNotified] = useState(false);
  const [opening, setOpening] = useState(false);
  const [whyOpen, setWhyOpen] = useState(false);

  // F5 interstitial — the branded commission-disclosure screen before the /out hop.
  const { open: openWithInterstitial, minting, interstitial } = useAffiliateOpen();

  const isAuth = !!session;

  // Resolve the id: try the real feed first, fall back to the mock catalog.
  useEffect(() => {
    if (!isAuth) return;
    let active = true;
    setResolving(true);

    (async () => {
      // 1) Try to resolve against the live feed (real productId path).
      try {
        const res = await getShopFeed({ cursor: 0, pageSize: 24 });
        const card = findInCards(res.cards, params.id);
        if (card) {
          if (active) {
            setProduct(fromCard(card));
            setResolving(false);
          }
          return;
        }
      } catch (err) {
        if (err instanceof ShopAuthError) {
          router.replace('/sign-in');
          return;
        }
        // Non-auth error: fall through to the mock catalog for display.
      }

      // 2) Mock catalog fallback (display only — no real productId).
      const mock = getShopProduct(params.id);
      if (active) {
        setProduct(mock ? fromMock(mock) : null);
        setResolving(false);
      }
    })();

    return () => {
      active = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isAuth, params.id]);

  useEffect(() => {
    if (product?.recommendedSize) setSize(product.recommendedSize);
  }, [product]);

  if (loading || !isAuth) return null;

  if (resolving) {
    return (
      <AppShell>
        <div style={{ padding: '52px 20px 40px' }}>
          <TopBar title="Product" />
          <div style={{ marginTop: 18 }}>
            <SkDetail />
          </div>
        </div>
      </AppShell>
    );
  }

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

  const canBuy = !!product.realProductId;

  const handleBuy = async () => {
    if (!product.realProductId) return;
    setOpening(true);
    logEvent({
      eventType: 'product_open',
      entityType: 'product',
      entityId: product.realProductId,
      source: 'product_detail',
    });
    try {
      // Real monetized redirect — mint click, then the F5 interstitial shows the
      // commission disclosure and does the top-level nav to /out/{clickId}.
      await openWithInterstitial(product.realProductId, 'product_detail', {
        brand: product.brand,
        detail: `${product.name} · $${product.price}`,
      });
      // The interstitial owns navigation from here.
    } catch {
      setOpening(false);
      setSavedNote('Couldn’t open the shop link. Try again.');
      setTimeout(() => setSavedNote(null), 2500);
    }
  };

  // In-stock alternatives for the OOS state — mock catalog, excluding this item.
  const alternatives: ShopProduct[] = SHOP_PRODUCTS.filter((p) => p.id !== params.id).slice(0, 2);

  return (
    <AppShell>
      <div style={{ padding: `52px 20px ${NAV_CLEAR}px` }}>
        <TopBar
          title="Product"
          right={
            <RoundBtn
              size={40}
              on={saved}
              aria-label={saved ? 'Saved on this device' : 'Save on this device'}
              icon={<Icon name="InterfaceBookmark" size={17} />}
              onClick={() =>
                setSaved((s) => {
                  const next = !s;
                  if (next) {
                    setSavedNote('Saved on this device');
                    setTimeout(() => setSavedNote(null), 2000);
                  }
                  return next;
                })
              }
              style={{ borderRadius: 14 }}
            />
          }
        />

        {/* Hero */}
        <div
          className="relative overflow-hidden"
          style={{ marginTop: 14, borderRadius: 26, height: 320, border: '1px solid rgba(255,255,255,0.12)' }}
        >
          <ItemImage src={product.imageUrl} alt={product.name} fit="cover" />
          <div
            className="pointer-events-none absolute inset-0"
            style={{ background: 'linear-gradient(to top, rgba(0,0,0,0.6), transparent 50%)' }}
            aria-hidden
          />
          {oos && (
            <span
              className="absolute"
              style={{
                top: 14,
                left: 14,
                padding: '6px 13px',
                borderRadius: 999,
                background: 'rgba(0,0,0,0.6)',
                backdropFilter: 'blur(10px)',
                WebkitBackdropFilter: 'blur(10px)',
                border: '1px solid rgba(255,255,255,0.22)',
                color: '#fff',
                fontSize: 11.5,
                fontWeight: 650,
              }}
            >
              Out of stock{product.recommendedSize ? ` in ${product.recommendedSize}` : ''}
            </span>
          )}
          {!oos && product.unlockCount != null && (
            <span
              className="absolute inline-flex items-center gap-1.5"
              style={{
                top: 14,
                left: 14,
                padding: '6px 12px',
                borderRadius: 999,
                background: 'rgba(0,0,0,0.5)',
                backdropFilter: 'blur(10px)',
                WebkitBackdropFilter: 'blur(10px)',
                border: '1px solid rgba(75,226,214,0.4)',
                color: 'var(--mint)',
                fontSize: 11,
                fontWeight: 650,
              }}
            >
              <Spark size={11} /> Unlocks {product.unlockCount} outfit
              {product.unlockCount === 1 ? '' : 's'}
            </span>
          )}
          <div className="absolute left-4 right-4 bottom-3.5 flex items-end justify-between">
            <div>
              <div className="text-[20px] font-bold tracking-[-0.4px] text-white">{product.name}</div>
              <div
                className="font-accent uppercase"
                style={{ color: 'rgba(255,255,255,0.65)', fontSize: 11, letterSpacing: '0.7px', marginTop: 2 }}
              >
                {product.brand} · ${product.price}
              </div>
            </div>
          </div>
        </div>

        {/* AI rationale — with a "Why?" affordance opening the transparency sheet. */}
        {product.reason && (
          <div
            className="mt-4 flex items-start gap-2.5 rounded-[14px]"
            style={{ padding: '13px 14px', ...M.ai(14) }}
          >
            <Spark size={15} />
            <span className="flex-1 text-[13.5px] leading-snug" style={{ color: M.soft }}>
              {product.reason}
            </span>
            <button
              type="button"
              onClick={() => setWhyOpen(true)}
              className="shrink-0 rounded-full text-[12px] font-semibold active:scale-95"
              style={{
                padding: '3px 11px',
                color: 'var(--mint)',
                background: 'rgba(75,226,214,0.1)',
                border: '1px solid rgba(75,226,214,0.3)',
                transition: 'transform 200ms var(--spring)',
              }}
            >
              Why?
            </button>
          </div>
        )}

        {/* Pairs-with strip — real goes-with (from the feed) when present. */}
        {product.goesWith && product.goesWith.length > 0 && (
          <>
            <div className="mt-5 mb-2.5 flex items-baseline justify-between">
              <span className="text-[15.5px] font-semibold text-white">Pairs with your closet</span>
              <span className="text-[11.5px]" style={{ color: M.ghost }}>
                {product.goesWith.length} of your pieces
              </span>
            </div>
            <div className="flex gap-2.5 overflow-x-auto pb-1" style={{ margin: '0 -20px', padding: '0 20px' }}>
              {product.goesWith.map((g, i) => (
                <div key={g.itemId ?? i} style={{ width: 84, flexShrink: 0 }}>
                  <ItemTile name={g.name ?? ''} imageUrl={g.imageUrl} />
                </div>
              ))}
            </div>
          </>
        )}

        {/* Out-of-stock — notify-me + in-stock alternatives. PRESENTATIONAL only:
            there is no stock field in the feed, so "notify me" is a device-local
            acknowledgement and alternatives come from the mock catalog. */}
        {oos && (
          <div style={{ marginTop: 18 }}>
            <div
              className="flex items-center gap-2.5 rounded-2xl"
              style={{
                padding: '11px 14px',
                background: 'rgba(75,226,214,0.10)',
                border: '1px solid rgba(75,226,214,0.28)',
              }}
            >
              <Bell size={15} style={{ color: 'var(--mint)', flexShrink: 0 }} />
              <span className="flex-1 text-[12.8px] leading-snug text-white">
                {notified
                  ? 'We’ll flag it here if it comes back (this device).'
                  : `Back-in-stock alerts${product.recommendedSize ? ` for size ${product.recommendedSize}` : ''}.`}
              </span>
              {!notified && (
                <button
                  type="button"
                  onClick={() => setNotified(true)}
                  className="whitespace-nowrap text-[12.5px] font-semibold"
                  style={{ color: 'var(--mint)' }}
                >
                  Notify me
                </button>
              )}
            </div>

            <div className="mt-4 mb-2.5 flex items-baseline justify-between">
              <span className="text-[15.5px] font-semibold text-white">Similar, in stock</span>
              <span className="text-[11px]" style={{ color: M.ghost }}>
                samples
              </span>
            </div>
            <div className="grid grid-cols-2 gap-3">
              {alternatives.map((s) => (
                <ItemTile
                  key={s.id}
                  name={s.name}
                  brand={s.brand}
                  imageUrl={s.img}
                  onClick={() => router.push(`/shop/${s.id}`)}
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
                      ${s.price}
                    </span>
                  }
                />
              ))}
            </div>
          </div>
        )}

        {/* Size selector — only when the source provides sizes (mock catalog). */}
        {!oos && product.sizes && product.sizes.length > 0 && (
          <>
            <div
              className="mt-5 mb-2.5 text-[12.5px] font-semibold"
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
          </>
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
        style={{ padding: '16px 20px 26px', background: 'linear-gradient(to top, rgba(30,30,30,0.98), transparent)' }}
      >
        <button
          type="button"
          aria-label={saved ? 'Saved on this device' : 'Save on this device'}
          onClick={() =>
            setSaved((s) => {
              const next = !s;
              if (next) {
                setSavedNote('Saved on this device');
                setTimeout(() => setSavedNote(null), 2000);
              }
              return next;
            })
          }
          className="flex shrink-0 items-center justify-center rounded-full"
          style={{
            width: 54,
            height: 50,
            border: '1px solid var(--tr-20)',
            background: 'rgba(0,0,0,0.3)',
            color: saved ? 'var(--mint)' : '#fff',
          }}
        >
          <Bookmark size={20} fill={saved ? 'currentColor' : 'none'} />
        </button>
        {oos ? (
          <Btn variant="glass" size="lg" fullWidth disabled title="Out of stock">
            Out of stock
          </Btn>
        ) : canBuy ? (
          <div className="flex-1">
            <Btn
              variant="primary"
              size="lg"
              fullWidth
              pending={opening || minting}
              icon={<ExternalLink size={16} />}
              onClick={handleBuy}
            >
              Shop {product.brand} · ${product.price}
            </Btn>
            <div className="mt-2 text-center text-[11px]" style={{ color: M.ghost }}>
              Opens {product.brand} · Tailor may earn a commission — never affects ranking
            </div>
          </div>
        ) : (
          <Btn variant="glass" size="lg" fullWidth disabled title="No shopping link yet">
            Shopping links coming soon
          </Btn>
        )}
      </div>

      {/* F5 interstitial — commission disclosure before the server-resolved /out hop. */}
      {interstitial}

      {/* §7 · P3 — transparency sheet. The real headline seeds the top reason;
          the rest are illustrative (no per-rec explanation endpoint yet). */}
      <WhyThisRecSheet
        open={whyOpen}
        onClose={() => setWhyOpen(false)}
        subject={`${product.name} · ${product.brand}`}
        reasons={
          product.reason
            ? [{ conf: 0.9, text: product.reason, evidence: 'the main reason Tailor surfaced this' }]
            : undefined
        }
      />
    </AppShell>
  );
}
