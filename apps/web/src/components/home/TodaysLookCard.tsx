'use client';

/**
 * Today's Look — the Home hero card. One auto-composed outfit for today
 * (weather + calendar + style profile), rendered as a single pure-white grid
 * collage, with "Wear this" + "Remix".
 *
 * Self-fetch pattern (module cache + freshness guard, NOT SWR), mirroring the
 * weather + calendar tiles: seed from cache for instant paint, revalidate in the
 * background. Fail-soft — getTodaysLook() never throws, so this card never
 * crashes Home; a thin closet renders a compact starter note instead.
 */
import { useEffect, useState } from 'react';
import { Check, Shuffle } from 'lucide-react';
import {
  getTodaysLook,
  getCachedTodaysLook,
  remixTodaysLook,
  wearTodaysLook,
  type TodaysLookResponse,
} from '@/lib/api/todays-look';
import { ItemImage } from '@/components/ui/ItemImage';
import { Btn, Spark, Sk, ImageFill, useToastStore, M } from '@/components/ds';

/** Cheap structural equality for the fields that drive the card — lets a
 * background revalidation skip the state swap (and its re-render) when the
 * look is unchanged. */
function sameLook(a: TodaysLookResponse, b: TodaysLookResponse): boolean {
  return (
    a.kind === b.kind &&
    a.collageUrl === b.collageUrl &&
    a.title === b.title &&
    a.caption === b.caption &&
    a.itemIds.join(',') === b.itemIds.join(',')
  );
}

export function TodaysLookCard() {
  const pushToast = useToastStore((s) => s.toast);
  const [look, setLook] = useState<TodaysLookResponse | null>(() => getCachedTodaysLook());
  const [loaded, setLoaded] = useState(() => getCachedTodaysLook() !== null);
  const [remixing, setRemixing] = useState(false);
  const [worn, setWorn] = useState(false);
  const [wearing, setWearing] = useState(false);

  // Cache-first: the cached look (if any) is already painted from the initial
  // state; ALWAYS revalidate in the background (the server half-day-caches, so
  // this is cheap) and swap only if the payload actually changed — no skeleton
  // flicker on navigation, no needless re-render when nothing moved.
  useEffect(() => {
    let alive = true;
    void getTodaysLook().then((r) => {
      if (!alive) return;
      setLoaded(true);
      setLook((prev) => (prev && sameLook(prev, r) ? prev : r));
    });
    return () => {
      alive = false;
    };
  }, []);

  // Cold client: a quiet skeleton (never a fake outfit).
  if (!loaded) {
    return (
      <div style={{ ...M.ai(24), overflow: 'hidden', marginTop: 20 }}>
        <Sk style={{ height: 200, borderRadius: 0 }} />
        <div style={{ padding: '13px 14px' }}>
          <Sk style={{ height: 14, width: '70%' }} />
          <Sk style={{ height: 12, width: '45%', marginTop: 8 }} />
        </div>
      </div>
    );
  }

  // Nothing to show (thin closet / unavailable) → nothing renders here; the
  // ranked feed below still carries the screen. Keeps Home uncluttered.
  if (!look || look.kind === 'starter' || look.itemIds.length === 0) {
    return null;
  }

  const slots = look.items.slice(0, 4);

  const onRemix = async () => {
    if (remixing) return;
    setRemixing(true);
    try {
      const next = await remixTodaysLook(look.itemIds);
      if (next.kind === 'normal' && next.itemIds.length > 0) {
        setLook(next);
        setWorn(false); // a new look hasn't been worn
      } else {
        pushToast({ tone: 'info', title: 'No other full look from your closet today.' });
      }
    } catch (err) {
      pushToast({ tone: 'error', title: err instanceof Error ? err.message : 'Remix failed.' });
    } finally {
      setRemixing(false);
    }
  };

  const onWear = async () => {
    if (worn || wearing) return;
    // Optimistic: mark worn immediately, confirm with the server.
    setWorn(true);
    setWearing(true);
    try {
      await wearTodaysLook(look.itemIds);
      pushToast({ tone: 'success', title: 'Saved — enjoy the look.' });
    } catch (err) {
      setWorn(false); // revert on failure
      pushToast({ tone: 'error', title: err instanceof Error ? err.message : 'Couldn’t save.' });
    } finally {
      setWearing(false);
    }
  };

  return (
    <div style={{ ...M.ai(24), overflow: 'hidden', marginTop: 20 }}>
      {/* Collage — server grid collage if present, else a 2×2 of items. The
          container matches the grid collage's aspect ratio (1080×720, 3:2) and its
          warm off-white bg (#F3EEE6) so a contain-fit image fills edge-to-edge with
          no letterbox frame. */}
      <div
        className="relative"
        style={{ aspectRatio: '1080 / 720', background: '#f3eee6' }}
      >
        {look.collageUrl ? (
          <ItemImage src={look.collageUrl} alt={look.title} fit="contain" />
        ) : slots.length > 0 ? (
          <div className="grid h-full w-full grid-cols-2 grid-rows-2" style={{ gap: 2 }}>
            {slots.map((s, i) => (
              <div key={s.id ?? i} className="relative overflow-hidden">
                <ItemImage src={s.imageUrl} alt={s.name ?? ''} fit="cover" />
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
          <Spark size={10} /> Today’s look
        </span>
      </div>

      <div style={{ padding: '13px 14px' }}>
        {look.title && (
          <div className="text-[15px] font-semibold tracking-[-0.2px] text-white" style={{ lineHeight: 1.3 }}>
            {look.title}
          </div>
        )}
        {look.caption && (
          <div className="mt-1 text-[12.5px] leading-snug" style={{ color: M.soft }}>
            {look.caption}
          </div>
        )}

        <div className="mt-3.5 flex gap-2">
          <Btn
            variant="primary"
            size="md"
            fullWidth
            pending={wearing}
            disabled={worn}
            icon={worn ? <Check size={16} strokeWidth={2.6} /> : undefined}
            onClick={() => void onWear()}
          >
            {worn ? 'Wearing this' : 'Wear this'}
          </Btn>
          <Btn
            variant="glass"
            size="md"
            pending={remixing}
            icon={<Shuffle size={15} strokeWidth={2.4} />}
            onClick={() => void onRemix()}
          >
            Remix
          </Btn>
        </div>
      </div>
    </div>
  );
}
