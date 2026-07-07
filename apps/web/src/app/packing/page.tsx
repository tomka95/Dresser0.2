'use client';

/**
 * /packing — §6 · F8 Packing list (ROADMAP preview).
 *
 * Trip header (destination · dates · temp) + a "pack these" checklist built from
 * the user's REAL closet items (useClosetStore for thumbnails / names). The trip
 * itself and the "N looks" figure come from the PACKING_MOCK shape — there is no
 * packing/trip backend, so:
 *   - the whole screen is labeled a "preview",
 *   - "Generate packing looks" is HONEST-disabled (no generator to call),
 *   - check-off is device-local only (local state, not persisted).
 *
 * If the closet is empty there is nothing to pack, so we show a calm empty state
 * that routes back to the closet rather than faking items. useRequireAuth guards.
 */

import { useEffect, useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import { Check, Luggage, Plus, Sparkles } from 'lucide-react';
import { useRequireAuth } from '@/lib/auth/useRequireAuth';
import { useClosetStore } from '@/stores/useClosetStore';
import { PACKING_MOCK } from '@/lib/mock/shop';
import { AppShell } from '@/components/layout/AppShell';
import { ItemImage } from '@/components/ui/ItemImage';
import { Btn, RoundBtn, TopBar, Spark, SkList, M, NAV_CLEAR } from '@/components/ds';

/** How many closet pieces the list previews (matches the mock's compact list). */
const PACK_COUNT = 5;

export default function PackingPage() {
  const router = useRouter();
  const { session, loading } = useRequireAuth();
  const isAuth = !!session;

  const items = useClosetStore((s) => s.items);
  const fetchItems = useClosetStore((s) => s.fetchItems);
  const hasFetchedItems = useClosetStore((s) => s.hasFetchedItems);
  const isLoading = useClosetStore((s) => s.isLoading);

  // Device-local check-off — a preview affordance, never persisted.
  const [checked, setChecked] = useState<Record<string, boolean>>({});

  useEffect(() => {
    if (isAuth && !hasFetchedItems) fetchItems();
  }, [isAuth, hasFetchedItems, fetchItems]);

  // Real closet pieces to pack (thumbnails + names come from the store).
  const packItems = useMemo(() => items.slice(0, PACK_COUNT), [items]);

  if (loading || !isAuth) return null;

  const fetching = isLoading && !hasFetchedItems;

  return (
    <AppShell>
      <div style={{ padding: `52px 20px ${NAV_CLEAR}px` }}>
        <TopBar
          title="Packing"
          sub={PACKING_MOCK.trip}
          right={
            <RoundBtn
              size={40}
              aria-label="Trip"
              icon={<Luggage size={17} />}
              style={{ borderRadius: 14 }}
            />
          }
        />

        {/* Preview banner — this whole surface is a roadmap preview. */}
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
          Preview · trip planning is coming soon
        </div>

        {/* AI look summary — MOCK figures (looks count / temp). The "Generate
            packing looks" action is honest-disabled: there is no generator. */}
        <div className="mt-4 flex items-center gap-3" style={{ ...M.ai(24), padding: 16 }}>
          <Spark size={15} />
          <div className="min-w-0 flex-1">
            <div className="text-[14.5px] font-semibold text-white">
              {PACKING_MOCK.looks} looks from {packItems.length || PACK_COUNT} pieces
            </div>
            <div style={{ color: M.faint, fontSize: 12, marginTop: 2 }}>
              {PACKING_MOCK.temp} all week — everything re-wears at least twice
            </div>
          </div>
          <Btn
            variant="mint"
            size="xs"
            disabled
            title="Packing looks are coming soon"
            icon={<Sparkles size={13} />}
          >
            Generate
          </Btn>
        </div>

        {fetching ? (
          <div className="mt-5">
            <SkList n={4} />
          </div>
        ) : packItems.length === 0 ? (
          /* Nothing to pack — route back to the closet rather than fake items. */
          <div
            className="mt-5 flex flex-col items-center text-center"
            style={{ ...M.glass(24), padding: '30px 22px' }}
          >
            <Luggage size={26} style={{ color: M.faint }} />
            <div className="mt-4 text-[16px] font-semibold text-white">
              Nothing to pack yet
            </div>
            <div className="mt-2 text-[13px] leading-relaxed" style={{ color: M.faint, maxWidth: 250 }}>
              Add pieces to your closet and they’ll show up here to pack for a trip.
            </div>
            <div className="mt-5 w-full" style={{ maxWidth: 220 }}>
              <Btn
                variant="primary"
                size="md"
                fullWidth
                icon={<Plus size={16} strokeWidth={2.4} />}
                onClick={() => router.push('/closet')}
              >
                Go to your closet
              </Btn>
            </div>
          </div>
        ) : (
          <>
            <div className="mx-0.5 mb-3 mt-5 flex items-baseline justify-between">
              <span className="text-[15.5px] font-semibold text-white">Pack these</span>
              <span className="text-[11.5px]" style={{ color: M.ghost }}>
                tap to check off
              </span>
            </div>
            <div className="flex flex-col gap-2.5">
              {packItems.map((it, i) => {
                const done = !!checked[it.id];
                return (
                  <button
                    key={it.id}
                    type="button"
                    onClick={() => setChecked((c) => ({ ...c, [it.id]: !c[it.id] }))}
                    className="flex w-full items-center gap-3 rounded-2xl text-left transition-opacity"
                    style={{
                      padding: '9px 12px',
                      background: 'rgba(255,255,255,0.05)',
                      border: '1px solid rgba(255,255,255,0.08)',
                      opacity: done ? 0.55 : 1,
                    }}
                    aria-pressed={done}
                  >
                    <span
                      className="flex shrink-0 items-center justify-center"
                      style={{
                        width: 22,
                        height: 22,
                        borderRadius: 8,
                        background: done ? 'var(--mint)' : 'rgba(255,255,255,0.08)',
                        border: done ? 'none' : '1.5px solid rgba(255,255,255,0.25)',
                        color: '#06302d',
                      }}
                    >
                      {done && <Check size={13} strokeWidth={3} />}
                    </span>
                    <div
                      className="relative overflow-hidden"
                      style={{ width: 38, height: 46, borderRadius: 10, flexShrink: 0 }}
                    >
                      <ItemImage src={it.imageUrl} alt={it.name} fit="cover" />
                    </div>
                    <div className="min-w-0 flex-1">
                      <div
                        className="truncate text-[13.5px] font-semibold text-white"
                        style={{ textDecoration: done ? 'line-through' : 'none' }}
                      >
                        {it.name}
                      </div>
                      <div style={{ color: M.faint, fontSize: 11 }}>in {i + 2} looks</div>
                    </div>
                  </button>
                );
              })}
            </div>
            <div className="mt-5 text-center text-[11px]" style={{ color: M.ghost }}>
              Look counts are a preview · packing looks aren’t generated yet
            </div>
          </>
        )}
      </div>
    </AppShell>
  );
}
