'use client';

/**
 * Home — the primary feed surface. Wires the REAL closet-aware Stage-1 feed
 * (GET /shop) as Home's ranked feed, replacing the old hardcoded weather/AI
 * mock cards.
 *
 * Feed cards are heterogeneous:
 *   - product cards: "Unlocks N", gap preview, price → tap expands a sheet with
 *     "goes with" thumbnails, then Shop → openProduct (mint click + /out).
 *   - outfit cards: collage + rationale + the single buyable piece → openProduct.
 *
 * Framing: "starter_looks" (cold start / near-empty closet) shows a starter
 * header; "personalized" shows the personalized header. Pagination uses the
 * sessionId watermark returned by page 1, echoed on every subsequent fetch.
 *
 * MONETIZATION: product opens go through openProduct() → POST /clicks → a real
 * top-level navigation to /out/{clickId}. No destination URL is ever built here.
 */

import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react';
import { useRouter } from 'next/navigation';
import { CloudRain, Cloud, Plus, Sun } from 'lucide-react';
import { useRequireAuth } from '@/lib/auth/useRequireAuth';
import { getCurrentUser } from '@/lib/api/auth';
import { getWeather, type WeatherResponse } from '@/lib/api/weather';
import { getCalendarToday, type CalendarTodayResponse } from '@/lib/api/calendar';
import { useClosetStore } from '@/stores/useClosetStore';
import { useOnline } from '@/lib/useOnline';
import { logEvent } from '@/lib/api/events';
import {
  getShopFeed,
  ShopAuthError,
  type Card,
  type ProductCard,
  type OutfitCard,
  type ShopFraming,
} from '@/lib/api/shop';
import { useAffiliateOpen } from '@/components/shop/useAffiliateOpen';
import { AppShell } from '@/components/layout/AppShell';
import { BottomNavBar } from '@/components/layout/BottomNavBar';
import { AddItemDrawer } from '@/components/closet/AddItemDrawer';
import { ItemImage } from '@/components/ui/ItemImage';
import {
  Btn,
  RoundBtn,
  Sheet,
  Spark,
  Icon,
  ItemTile,
  ImageFill,
  ErrorState,
  OfflineScreen,
  SkFeed,
  useToastStore,
  M,
  NAV_CLEAR,
} from '@/components/ds';

const PAGE_SIZE = 8;

export default function HomePage() {
  const router = useRouter();
  // Gate on the Supabase session AND onboarding completion; a not-onboarded user
  // is redirected to /onboarding before any home chrome renders (no flash).
  const { session, loading } = useRequireAuth('/sign-in', { requireOnboarded: true });
  const isAuth = !!session;
  const online = useOnline();
  const pushToast = useToastStore((s) => s.toast);

  const items = useClosetStore((s) => s.items);
  const fetchItems = useClosetStore((s) => s.fetchItems);
  const hasFetchedItems = useClosetStore((s) => s.hasFetchedItems);

  const [firstName, setFirstName] = useState<string | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);

  // Feed state.
  const [cards, setCards] = useState<Card[]>([]);
  const [framing, setFraming] = useState<ShopFraming>('personalized');
  const [cursor, setCursor] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  // sessionId watermark — captured from page 1, echoed on every next fetch so
  // the ranker keeps a stable view across pages.
  const [feedSessionId, setFeedSessionId] = useState<string | undefined>(undefined);
  const [feedLoading, setFeedLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [feedError, setFeedError] = useState(false);

  // Expanded product sheet (goes-with preview + Shop CTA).
  const [expanded, setExpanded] = useState<ProductCard | null>(null);
  const [opening, setOpening] = useState(false);
  // F5 interstitial — commission disclosure before the /out hop.
  const { open: openWithInterstitial, minting, interstitial } = useAffiliateOpen();

  // Impressions already logged (feedPosition-keyed) so scroll re-renders don't double-count.
  const seen = useRef<Set<number>>(new Set());

  useEffect(() => {
    if (isAuth && !hasFetchedItems) fetchItems();
  }, [isAuth, hasFetchedItems, fetchItems]);

  // Greeting name: backend profile first, session metadata as fallback.
  useEffect(() => {
    if (!isAuth) return;
    let active = true;
    getCurrentUser()
      .then((u) => {
        if (!active) return;
        const name = u.display_name || u.full_name;
        if (name) setFirstName(name.trim().split(/\s+/)[0]);
      })
      .catch(() => {
        const meta = (session?.user?.user_metadata ?? {}) as { full_name?: string };
        if (active && meta.full_name) setFirstName(meta.full_name.trim().split(/\s+/)[0]);
      });
    return () => {
      active = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isAuth]);

  const loadFeed = useCallback(async () => {
    setFeedLoading(true);
    setFeedError(false);
    seen.current.clear();
    try {
      const res = await getShopFeed({ cursor: 0, pageSize: PAGE_SIZE });
      setCards(res.cards);
      setFraming(res.framing);
      setCursor(res.cursor);
      setHasMore(res.hasMore);
      setFeedSessionId(res.sessionId);
    } catch (err) {
      if (err instanceof ShopAuthError) {
        router.replace('/sign-in');
        return;
      }
      setFeedError(true);
    } finally {
      setFeedLoading(false);
    }
  }, [router]);

  useEffect(() => {
    if (isAuth && online) void loadFeed();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isAuth, online]);

  const loadMore = useCallback(async () => {
    if (loadingMore || !hasMore) return;
    setLoadingMore(true);
    try {
      const res = await getShopFeed({
        cursor,
        sessionId: feedSessionId, // echo the page-1 watermark
        pageSize: PAGE_SIZE,
      });
      setCards((prev) => [...prev, ...res.cards]);
      setCursor(res.cursor);
      setHasMore(res.hasMore);
    } catch {
      pushToast({ tone: 'error', title: 'Couldn’t load more. Try again.' });
    } finally {
      setLoadingMore(false);
    }
  }, [loadingMore, hasMore, cursor, feedSessionId, pushToast]);

  // Impression telemetry — fire once per card as it first renders.
  const logImpression = useCallback((c: Card) => {
    if (seen.current.has(c.feedPosition)) return;
    seen.current.add(c.feedPosition);
    logEvent({
      eventType: 'feed_impression',
      entityType: c.cardType,
      entityId: c.type === 'product' ? c.product.productId : c.buyable?.productId,
      source: 'home_feed',
      properties: {
        feedPosition: c.feedPosition,
        cardType: c.cardType,
        exploration: !!c.exploration?.isExploration,
      },
    });
  }, []);

  const handleOpenProduct = useCallback(
    async (
      productId: string,
      surface: string,
      card: Card,
      display: { brand: string; name: string; price: number },
    ) => {
      setOpening(true);
      logEvent({
        eventType: 'product_open',
        entityType: 'product',
        entityId: productId,
        source: surface,
        properties: {
          feedPosition: card.feedPosition,
          cardType: card.cardType,
          exploration: !!card.exploration?.isExploration,
        },
      });
      try {
        // Real monetized redirect: mint click → F5 interstitial (disclosure) →
        // top-level nav to /out/{clickId}. No destination URL is built here.
        await openWithInterstitial(productId, surface, {
          brand: display.brand,
          detail: `${display.name} · $${display.price}`,
        });
        // The interstitial owns navigation from here.
      } catch {
        setOpening(false);
        pushToast({ tone: 'error', title: 'Couldn’t open this product. Try again.' });
      }
    },
    [openWithInterstitial, pushToast],
  );

  if (loading || !isAuth) return null;

  const starter = framing === 'starter_looks';
  const closetStrip = items.slice(0, 8);
  const today = new Date().toLocaleDateString(undefined, {
    weekday: 'long',
    month: 'short',
    day: 'numeric',
  });

  return (
    <AppShell>
      <div style={{ padding: `56px 20px ${NAV_CLEAR}px` }}>
        {/* Greeting */}
        <div className="flex items-start justify-between">
          <div>
            <div
              className="uppercase"
              style={{ color: M.ghost, fontSize: 11, fontWeight: 650, letterSpacing: '0.13em' }}
            >
              {today}
            </div>
            <h1 className="m-0 mt-1 text-[31px] font-bold tracking-[-0.9px] text-white">
              Hey, {firstName ?? 'there'}
            </h1>
          </div>
          <RoundBtn
            size={42}
            aria-label="Add to closet"
            icon={<Plus size={18} strokeWidth={2.6} />}
            onClick={() => setDrawerOpen(true)}
          />
        </div>

        {/* Bento: weather + calendar tiles — both REAL now (GET /weather, GET
            /calendar/today), each degrading quietly when unavailable. The ranked
            feed below is the REAL /shop surface. */}
        {online && !starter && (
          <HomeBentoTiles />
        )}

        {/* Closet strip — REAL closet items (client store). Skipped while empty
            so a cold-start user isn't shown an empty rail. */}
        {closetStrip.length > 0 && (
          <>
            <div className="mx-0.5 mb-3 mt-6 flex items-baseline justify-between">
              <span className="text-[17px] font-semibold tracking-[-0.3px] text-white">
                Your closet
              </span>
              <button
                type="button"
                onClick={() => router.push('/closet')}
                className="text-[12.5px] font-semibold"
                style={{ color: 'var(--mint)' }}
              >
                See all {items.length}
              </button>
            </div>
            <div className="flex gap-2.5 overflow-x-auto pb-1" style={{ margin: '0 -20px', padding: '0 20px 4px' }}>
              {closetStrip.map((it) => (
                <div key={it.id} style={{ width: 108, flexShrink: 0 }}>
                  <ItemTile
                    name={it.name}
                    brand={it.brand}
                    imageUrl={it.imageUrl}
                    onClick={() => router.push(`/closet/${it.id}`)}
                  />
                </div>
              ))}
            </div>
          </>
        )}

        {/* Feed header — framing-aware. LOCKED trust line under both. */}
        <div style={{ marginTop: 22 }}>
          {starter ? (
            <>
              <div className="text-[22px] font-bold tracking-[-0.5px] text-white">
                Starter looks to get going
              </div>
              <div className="mt-1 text-[13.5px]" style={{ color: M.faint }}>
                Add a few pieces and this feed learns your closet.
              </div>
            </>
          ) : (
            <>
              <div className="text-[22px] font-bold tracking-[-0.5px] text-white">
                Worth adding
              </div>
              <div className="mt-1 text-[13.5px]" style={{ color: M.faint }}>
                Ranked for your wardrobe, not for commission.
              </div>
            </>
          )}
        </div>

        {/* Feed body */}
        <div style={{ marginTop: 16 }}>
          {!online ? (
            <OfflineScreen
              context="Your feed needs a connection. Your closet is saved on this phone."
              onRetry={() => void loadFeed()}
              onBrowseCloset={() => router.push('/closet')}
            />
          ) : feedLoading ? (
            <SkFeed />
          ) : feedError ? (
            <ErrorState
              title="Feed didn’t load"
              sub="We couldn’t rank your feed just now. Your closet is untouched."
              onRetry={() => void loadFeed()}
            />
          ) : cards.length === 0 ? (
            <StarterEmpty onAdd={() => setDrawerOpen(true)} />
          ) : (
            <>
              <div className="flex flex-col" style={{ gap: 14 }}>
                {cards.map((c) =>
                  c.type === 'product' ? (
                    <ProductFeedCard
                      key={`p-${c.feedPosition}-${c.product.productId}`}
                      card={c}
                      onImpression={logImpression}
                      onExpand={() => setExpanded(c)}
                    />
                  ) : (
                    <OutfitFeedCard
                      key={`o-${c.feedPosition}`}
                      card={c}
                      onImpression={logImpression}
                      onBuy={() =>
                        c.buyable &&
                        handleOpenProduct(c.buyable.productId, 'home_outfit_card', c, {
                          brand: c.buyable.brand,
                          name: c.buyable.name,
                          price: c.buyable.price,
                        })
                      }
                    />
                  ),
                )}
              </div>

              {/* Pagination */}
              {hasMore ? (
                <div className="mt-5 flex justify-center">
                  <Btn variant="glass" size="md" pending={loadingMore} onClick={() => void loadMore()}>
                    Load more
                  </Btn>
                </div>
              ) : (
                <div
                  className="mt-6 text-center text-[11.5px]"
                  style={{ color: M.ghost }}
                >
                  That’s everything ranked for your closet today.
                </div>
              )}
            </>
          )}
        </div>
      </div>

      {/* Expanded product sheet — goes-with preview + honest Shop CTA. */}
      <Sheet
        open={!!expanded}
        onClose={() => setExpanded(null)}
        title={expanded?.product.name}
        sub={expanded ? `${expanded.product.brand} · $${expanded.product.price}` : undefined}
      >
        {expanded && (
          <div>
            <div
              className="flex items-center gap-2"
              style={{ color: 'var(--mint)', fontSize: 12.5, fontWeight: 650 }}
            >
              <Spark size={12} /> {expanded.headline}
            </div>

            {expanded.goesWith && expanded.goesWith.length > 0 && (
              <>
                <div
                  className="mt-4 mb-2.5 text-[13px] font-semibold text-white"
                >
                  Goes with your closet
                </div>
                <div className="flex gap-2.5 overflow-x-auto pb-1">
                  {expanded.goesWith.map((g, i) => (
                    <div key={g.itemId ?? i} style={{ width: 70, flexShrink: 0 }}>
                      <div
                        className="relative overflow-hidden rounded-xl"
                        style={{ aspectRatio: '3 / 4', border: '1px solid rgba(255,255,255,0.1)' }}
                      >
                        <ItemImage src={g.imageUrl} alt={g.name ?? ''} fit="cover" />
                      </div>
                    </div>
                  ))}
                </div>
              </>
            )}

            <div className="mt-5 flex flex-col gap-2">
              <Btn
                variant="primary"
                size="lg"
                fullWidth
                pending={opening || minting}
                icon={<Icon name="ArrowChevronRightMD" size={16} />}
                onClick={() =>
                  handleOpenProduct(expanded.product.productId, 'home_product_sheet', expanded, {
                    brand: expanded.product.brand,
                    name: expanded.product.name,
                    price: expanded.product.price,
                  })
                }
              >
                Shop {expanded.product.brand} · ${expanded.product.price}
              </Btn>
              <div className="text-center text-[11px]" style={{ color: M.ghost }}>
                Tailor may earn a commission — it never affects ranking.
              </div>
            </div>
          </div>
        )}
      </Sheet>

      <AddItemDrawer
        open={drawerOpen}
        onOpenChange={setDrawerOpen}
        onGmailClick={() => {
          setDrawerOpen(false);
          router.push('/review');
        }}
      />

      <BottomNavBar activeRoute="/home" />

      {/* F5 interstitial — commission disclosure before the server-resolved /out hop. */}
      {interstitial}
    </AppShell>
  );
}

/* ── Cards ────────────────────────────────────────────────────────────────── */

function ProductFeedCard({
  card,
  onImpression,
  onExpand,
}: {
  card: ProductCard;
  onImpression: (c: Card) => void;
  onExpand: () => void;
}) {
  const explore = !!card.exploration?.isExploration;
  useEffect(() => {
    onImpression(card);
  }, [card, onImpression]);

  return (
    <button
      type="button"
      onClick={onExpand}
      className="block w-full text-left"
      style={{ ...M.glass(24), overflow: 'hidden' }}
    >
      <div className="relative" style={{ height: 210 }}>
        <ItemImage src={card.product.imageUrl} alt={card.product.name} fit="cover" />
        <div
          className="pointer-events-none absolute inset-0"
          style={{ background: 'linear-gradient(to top, rgba(0,0,0,0.55), transparent 45%)' }}
          aria-hidden
        />
        {/* Unlock / exploration badge — exploration is labeled honestly. */}
        <span
          className="absolute inline-flex items-center gap-1.5"
          style={{
            top: 11,
            left: 11,
            padding: '5px 11px',
            borderRadius: 999,
            background: explore ? 'rgba(150,120,230,0.2)' : 'rgba(0,0,0,0.5)',
            backdropFilter: 'blur(10px)',
            WebkitBackdropFilter: 'blur(10px)',
            border: explore ? '1px solid rgba(150,120,230,0.5)' : '1px solid rgba(75,226,214,0.4)',
            color: explore ? '#c9bcf5' : 'var(--mint)',
            fontSize: 10.5,
            fontWeight: 650,
          }}
        >
          {explore ? (
            'Outside your lane — on purpose'
          ) : (
            <>
              <Spark size={10} /> Unlocks {card.unlockCount} outfit
              {card.unlockCount === 1 ? '' : 's'}
            </>
          )}
        </span>
        <div className="absolute left-3.5 right-3.5 bottom-3 flex items-end justify-between">
          <div>
            <div className="text-[15px] font-semibold text-white">{card.product.name}</div>
            <div
              className="font-accent uppercase"
              style={{ color: 'rgba(255,255,255,0.65)', fontSize: 10.5, letterSpacing: '0.6px' }}
            >
              {card.product.brand}
            </div>
          </div>
          <span className="text-[15px] font-bold text-white">${card.product.price}</span>
        </div>
      </div>
      <div className="flex items-center gap-2.5" style={{ padding: '11px 14px' }}>
        <span className="flex-1 text-[11.5px]" style={{ color: M.faint }}>
          {card.headline}
        </span>
        <Icon name="ArrowChevronRightMD" size={15} style={{ color: M.ghost }} />
      </div>
    </button>
  );
}

function OutfitFeedCard({
  card,
  onImpression,
  onBuy,
}: {
  card: OutfitCard;
  onImpression: (c: Card) => void;
  onBuy: () => void;
}) {
  useEffect(() => {
    onImpression(card);
  }, [card, onImpression]);

  const slots = (card.slots ?? []).slice(0, 4);

  return (
    <div style={{ ...M.ai(24), overflow: 'hidden' }}>
      {/* Collage — server collageUrl if present, else a 2×2 of the slots. */}
      <div className="relative" style={{ height: 200 }}>
        {card.collageUrl ? (
          <ItemImage src={card.collageUrl} alt="" fit="cover" />
        ) : slots.length > 0 ? (
          <div className="grid h-full w-full grid-cols-2 grid-rows-2" style={{ gap: 2 }}>
            {slots.map((s, i) => (
              <div key={s.itemId ?? i} className="relative overflow-hidden">
                <ItemImage src={s.product?.imageUrl ?? s.imageUrl} alt={s.name ?? ''} fit="cover" />
              </div>
            ))}
          </div>
        ) : (
          <ImageFill ratio="auto" radius={0} style={{ height: '100%' }} />
        )}
        <span
          className="absolute inline-flex items-center gap-1.5"
          style={{
            top: 11,
            left: 11,
            padding: '5px 11px',
            borderRadius: 999,
            background: 'rgba(0,0,0,0.5)',
            backdropFilter: 'blur(10px)',
            WebkitBackdropFilter: 'blur(10px)',
            border: '1px solid rgba(75,226,214,0.4)',
            color: 'var(--mint)',
            fontSize: 10.5,
            fontWeight: 650,
          }}
        >
          <Spark size={10} /> A look, mostly from your closet
        </span>
      </div>
      <div style={{ padding: '13px 14px' }}>
        <div className="text-[12.5px] leading-snug" style={{ color: M.soft }}>
          {card.rationale}
        </div>
        {card.buyable && (
          <div
            className="mt-3 flex items-center gap-2.5 rounded-2xl"
            style={{ padding: '9px 11px', background: 'rgba(255,255,255,0.06)', border: M.hair }}
          >
            <div
              className="relative overflow-hidden rounded-lg"
              style={{ width: 40, height: 48, flexShrink: 0 }}
            >
              <ItemImage src={card.buyable.imageUrl} alt={card.buyable.name} fit="cover" />
            </div>
            <div className="min-w-0 flex-1">
              <div className="truncate text-[13px] font-semibold text-white">
                {card.buyable.name}
              </div>
              <div className="text-[11px]" style={{ color: M.faint }}>
                {card.buyable.brand} · ${card.buyable.price} · the one piece to add
              </div>
            </div>
            <Btn variant="primary" size="sm" onClick={onBuy}>
              Shop
            </Btn>
          </div>
        )}
      </div>
    </div>
  );
}

/** Real weather tile — self-fetches GET /weather, degrades quietly. */
function WeatherTile() {
  const [wx, setWx] = useState<WeatherResponse | null>(null);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    let alive = true;
    void getWeather().then((r) => {
      if (alive) {
        setWx(r);
        setLoaded(true);
      }
    });
    return () => {
      alive = false;
    };
  }, []);

  const tile = (children: ReactNode) => (
    <div style={{ ...M.glass(24), padding: '15px 16px', position: 'relative' }}>{children}</div>
  );

  // Loading or unavailable → muted placeholder (never fake numbers).
  if (!loaded) {
    return tile(<div style={{ color: M.ghost, fontSize: 11.5 }}>Weather…</div>);
  }
  if (!wx?.available || !wx.current || !wx.today) {
    const msg = wx?.reason === 'no_location' ? 'Set your location' : 'Weather unavailable';
    return tile(
      <div className="flex items-center gap-2.5">
        <Cloud size={26} style={{ color: M.ghost }} />
        <div style={{ color: M.faint, fontSize: 12 }}>{msg}</div>
      </div>,
    );
  }

  const { current, today } = wx;
  const wet = current.precip_mm > 0 || (today.precip_chance_pct ?? 0) >= 50;
  const Icon = wet ? CloudRain : Sun;
  return tile(
    <>
      <div className="flex items-center gap-2.5">
        <Icon size={26} style={{ color: wet ? M.ghost : '#f5d78e' }} />
        <div>
          <div className="text-[21px] font-bold tracking-[-0.4px] text-white">
            {Math.round(current.temp_c)}°
          </div>
          <div style={{ color: M.faint, fontSize: 11.5 }}>{current.condition}</div>
        </div>
      </div>
      <div className="mt-2.5 flex items-center gap-1.5" style={{ color: M.faint, fontSize: 11.5 }}>
        <span>
          H {Math.round(today.high_c)}° · L {Math.round(today.low_c)}°
        </span>
        {today.precip_chance_pct != null && today.precip_chance_pct >= 30 && (
          <span style={{ color: M.ghost }}>· {today.precip_chance_pct}% rain</span>
        )}
      </div>
    </>,
  );
}

/**
 * Bento tiles — weather + calendar, both REAL and self-fetching.
 *
 * Weather: GET /weather (conditions + today's range + warmth band from the saved
 * location). Calendar: GET /calendar/today (live events for a connected user).
 * Each fails soft to a muted placeholder rather than fake data.
 */
function HomeBentoTiles() {
  return (
    <div className="grid gap-3" style={{ gridTemplateColumns: '1.15fr 1fr', marginTop: 20 }}>
      <WeatherTile />
      <CalendarTile />
    </div>
  );
}

/** Real calendar tile — self-fetches GET /calendar/today, degrades quietly. */
function CalendarTile() {
  const [data, setData] = useState<CalendarTodayResponse | null>(null);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    let alive = true;
    void getCalendarToday().then((r) => {
      if (alive) {
        setData(r);
        setLoaded(true);
      }
    });
    return () => {
      alive = false;
    };
  }, []);

  const shell = (children: ReactNode) => (
    <div style={{ ...M.glass(24), padding: '15px 16px', position: 'relative' }}>
      <div
        className="uppercase"
        style={{ color: M.ghost, fontSize: 10, fontWeight: 650, letterSpacing: '0.13em' }}
      >
        Today
      </div>
      {children}
    </div>
  );

  if (!loaded) {
    return shell(<div className="mt-1.5" style={{ color: M.ghost, fontSize: 12 }}>Calendar…</div>);
  }
  // Not connected → a quiet invitation (no fake events).
  if (!data?.connected) {
    return shell(
      <div className="mt-1.5" style={{ color: M.faint, fontSize: 12, lineHeight: 1.35 }}>
        Connect your calendar to dress for your day
      </div>,
    );
  }
  if (data.events.length === 0) {
    return shell(<div className="mt-1.5" style={{ color: M.faint, fontSize: 12 }}>Nothing on today</div>);
  }
  const [first, ...rest] = data.events;
  return shell(
    <>
      <div className="mt-1.5 text-[13.5px] font-semibold text-white" style={{ lineHeight: 1.35 }}>
        {first.summary}
        <br />
        <span style={{ color: M.faint, fontWeight: 450, fontSize: 12 }}>
          {first.start}
          {first.location ? ` · ${first.location}` : ''}
        </span>
      </div>
      {rest.slice(0, 1).map((e, i) => (
        <div key={i} className="mt-1.5 truncate" style={{ color: M.faint, fontSize: 12 }}>
          {e.summary} · {e.start}
        </div>
      ))}
    </>,
  );
}

/** Cold-start / empty feed — seed the closet. */
function StarterEmpty({ onAdd }: { onAdd: () => void }) {
  return (
    <div
      className="flex flex-col items-center text-center"
      style={{ ...M.glass(26), padding: '30px 22px' }}
    >
      <Spark size={26} />
      <div className="mt-4 text-[18px] font-bold tracking-[-0.4px] text-white">
        Your feed is warming up
      </div>
      <div className="mt-2 text-[13.5px] leading-relaxed" style={{ color: M.faint, maxWidth: 260 }}>
        Add a few pieces and Tailor starts ranking what actually completes your closet.
      </div>
      <div className="mt-5 w-full" style={{ maxWidth: 240 }}>
        <Btn variant="primary" size="md" fullWidth icon={<Plus size={16} strokeWidth={2.4} />} onClick={onAdd}>
          Add your first pieces
        </Btn>
      </div>
    </div>
  );
}
