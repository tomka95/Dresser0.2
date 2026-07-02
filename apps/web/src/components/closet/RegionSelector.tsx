'use client';

/**
 * RegionSelector — Wave 1.5 "document scanner" step for photo ingestion.
 *
 * Shows one picked photo at a time with the garment regions the backend detected
 * pre-highlighted (all selected). The user taps regions on/off, can draw a missed
 * region by hand (max 8 per photo), steps through the photos, and commits with
 * "Add N items". Duplicate photos (already in the closet pipeline) render as a
 * skipped tile with an "Already added" badge.
 *
 * Geometry: the photo renders object-contain inside the frame; the overlay is an
 * absolutely-positioned div at the CONTAINED image rect (letterboxing math from the
 * measured frame size + the detect response's width/height), and every box inside
 * it is percentage-positioned from box_2d/1000 — so overlays align exactly at any
 * viewport size. No canvas: plain divs + pointer events.
 */

import React, {
  useCallback,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import { motion } from 'framer-motion';
import { Check, ChevronLeft, ChevronRight, Plus, X } from 'lucide-react';

import type { PhotoCommitSelection, PhotoDetectSession } from '@/lib/api/gmail';
import { DSButton } from '@/components/ds';

export interface RegionPhoto {
  /** Local object URL of the picked File (never a network fetch). */
  previewUrl: string;
  /** The detect session for this photo (same index as the file sent). */
  session: PhotoDetectSession;
}

interface RegionSelectorProps {
  photos: RegionPhoto[];
  /** True while the commit request is in flight — locks the UI. */
  committing?: boolean;
  onCancel: () => void;
  onCommit: (selections: PhotoCommitSelection[]) => void;
}

type Box = [number, number, number, number]; // [ymin, xmin, ymax, xmax] 0..1000

interface ManualBox {
  id: number;
  box: Box;
}

interface PhotoSelection {
  regionIds: Set<number>;
  manual: ManualBox[];
}

const MAX_MANUAL_BOXES = 8;
/** Minimum drag size (fraction of the displayed image per dimension) to keep a drawn box. */
const MIN_DRAW_FRACTION = 0.04;

const pct = (v: number) => `${v / 10}%`; // 0..1000 → CSS %
const boxArea = ([ymin, xmin, ymax, xmax]: Box) =>
  Math.max(0, ymax - ymin) * Math.max(0, xmax - xmin);
const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));

/** Small glass label chip shown at a box's top-left corner. */
function BoxLabel({ name }: { name: string }) {
  return (
    <span
      className="absolute left-1 top-1 max-w-[92%] truncate rounded-md px-1.5 py-0.5 text-[10px] font-medium text-white"
      style={{
        background: 'rgba(0,0,0,0.55)',
        border: '1px solid var(--tr-20)',
        backdropFilter: 'blur(6px)',
        WebkitBackdropFilter: 'blur(6px)',
      }}
    >
      {name}
    </span>
  );
}

export function RegionSelector({
  photos,
  committing = false,
  onCancel,
  onCommit,
}: RegionSelectorProps) {
  // Open on the first photo the user can actually work on (skip leading duplicates).
  const [index, setIndex] = useState(() =>
    Math.max(
      0,
      photos.findIndex((p) => !p.session.duplicate),
    ),
  );

  // Per-photo selection state, same order as `photos`. Every detected region starts
  // selected — the scanner presents what it found and the user prunes.
  const [selections, setSelections] = useState<PhotoSelection[]>(() =>
    photos.map((p) => ({
      regionIds: new Set(p.session.regions.map((r) => r.region_id)),
      manual: [],
    })),
  );

  const [drawMode, setDrawMode] = useState(false);
  // Live rubber-band rect while drawing, in px relative to the displayed image rect.
  const [draft, setDraft] = useState<{ x: number; y: number; w: number; h: number } | null>(null);
  const drawStartRef = useRef<{ x: number; y: number } | null>(null);
  const manualSeqRef = useRef(0);

  // ── Measure the photo frame so the contained image rect can be computed ────
  const frameRef = useRef<HTMLDivElement>(null);
  const [frame, setFrame] = useState({ w: 0, h: 0 });

  useLayoutEffect(() => {
    const el = frameRef.current;
    if (!el) return;
    const measure = () => {
      const r = el.getBoundingClientRect();
      setFrame((prev) => (prev.w === r.width && prev.h === r.height ? prev : { w: r.width, h: r.height }));
    };
    measure();
    if (typeof ResizeObserver !== 'undefined') {
      const ro = new ResizeObserver(measure);
      ro.observe(el);
      return () => ro.disconnect();
    }
    window.addEventListener('resize', measure);
    return () => window.removeEventListener('resize', measure);
  }, []);

  const current = photos[index];
  const sel = selections[index];
  const isDup = current.session.duplicate || !current.session.session_id;
  const atManualCap = sel.manual.length >= MAX_MANUAL_BOXES;

  // Contain-fit letterboxing: where the photo actually paints inside the frame.
  const iw = current.session.width;
  const ih = current.session.height;
  const scale = frame.w > 0 && frame.h > 0 && iw > 0 && ih > 0 ? Math.min(frame.w / iw, frame.h / ih) : 0;
  const dw = iw * scale;
  const dh = ih * scale;
  const ox = (frame.w - dw) / 2;
  const oy = (frame.h - dh) / 2;

  // Overlapping boxes: stack by area so the SMALLEST box paints on top and wins the
  // tap wherever boxes overlap (its non-overlapped siblings still get their own hits).
  const orderedRegions = useMemo(
    () => current.session.regions.slice().sort((a, b) => boxArea(b.box_2d) - boxArea(a.box_2d)),
    [current.session],
  );

  const totalSelected = useMemo(
    () =>
      selections.reduce(
        (sum, s, i) =>
          photos[i].session.duplicate ? sum : sum + s.regionIds.size + s.manual.length,
        0,
      ),
    [selections, photos],
  );

  // ── Selection mutations ─────────────────────────────────────────────────────
  const toggleRegion = useCallback(
    (regionId: number) => {
      if (committing) return;
      setSelections((prev) =>
        prev.map((s, i) => {
          if (i !== index) return s;
          const next = new Set(s.regionIds);
          if (next.has(regionId)) next.delete(regionId);
          else next.add(regionId);
          return { ...s, regionIds: next };
        }),
      );
    },
    [index, committing],
  );

  const removeManual = useCallback(
    (id: number) => {
      if (committing) return;
      setSelections((prev) =>
        prev.map((s, i) => (i === index ? { ...s, manual: s.manual.filter((m) => m.id !== id) } : s)),
      );
    },
    [index, committing],
  );

  const goTo = useCallback(
    (next: number) => {
      setIndex(clamp(next, 0, photos.length - 1));
      setDrawMode(false);
      setDraft(null);
      drawStartRef.current = null;
    },
    [photos.length],
  );

  // ── Draw-a-missed-region (pointer events; touch + mouse) ───────────────────
  const onDrawDown = (e: React.PointerEvent<HTMLDivElement>) => {
    if (committing) return;
    const rect = e.currentTarget.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0) return;
    const x = clamp(e.clientX - rect.left, 0, rect.width);
    const y = clamp(e.clientY - rect.top, 0, rect.height);
    drawStartRef.current = { x, y };
    setDraft({ x, y, w: 0, h: 0 });
    e.currentTarget.setPointerCapture?.(e.pointerId);
  };

  const onDrawMove = (e: React.PointerEvent<HTMLDivElement>) => {
    const start = drawStartRef.current;
    if (!start) return;
    const rect = e.currentTarget.getBoundingClientRect();
    const cx = clamp(e.clientX - rect.left, 0, rect.width);
    const cy = clamp(e.clientY - rect.top, 0, rect.height);
    setDraft({
      x: Math.min(start.x, cx),
      y: Math.min(start.y, cy),
      w: Math.abs(cx - start.x),
      h: Math.abs(cy - start.y),
    });
  };

  const onDrawUp = (e: React.PointerEvent<HTMLDivElement>) => {
    const start = drawStartRef.current;
    drawStartRef.current = null;
    setDraft(null);
    if (!start) return;
    const rect = e.currentTarget.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0) return;
    const cx = clamp(e.clientX - rect.left, 0, rect.width);
    const cy = clamp(e.clientY - rect.top, 0, rect.height);
    const x0 = Math.min(start.x, cx);
    const y0 = Math.min(start.y, cy);
    const w = Math.abs(cx - start.x);
    const h = Math.abs(cy - start.y);
    // Accidental taps / slivers: require ~4% of the image in each dimension.
    if (w < rect.width * MIN_DRAW_FRACTION || h < rect.height * MIN_DRAW_FRACTION) return;
    const box: Box = [
      clamp(Math.round((y0 / rect.height) * 1000), 0, 1000),
      clamp(Math.round((x0 / rect.width) * 1000), 0, 1000),
      clamp(Math.round(((y0 + h) / rect.height) * 1000), 0, 1000),
      clamp(Math.round(((x0 + w) / rect.width) * 1000), 0, 1000),
    ];
    setSelections((prev) =>
      prev.map((s, i) =>
        i === index && s.manual.length < MAX_MANUAL_BOXES
          ? { ...s, manual: [...s.manual, { id: ++manualSeqRef.current, box }] }
          : s,
      ),
    );
    setDrawMode(false); // one box per gesture — tap "Add item" again for another
  };

  const onDrawCancel = () => {
    drawStartRef.current = null;
    setDraft(null);
  };

  // ── Commit payload — only live (non-duplicate) sessions carry selections ───
  const buildSelections = useCallback((): PhotoCommitSelection[] => {
    return photos.flatMap((p, i) => {
      const s = p.session;
      if (s.duplicate || !s.session_id) return [];
      const chosen = selections[i];
      return [
        {
          session_id: s.session_id,
          selected_region_ids: s.regions
            .filter((r) => chosen.regionIds.has(r.region_id))
            .map((r) => r.region_id),
          manual_boxes: chosen.manual.map((m) => m.box),
        },
      ];
    });
  }, [photos, selections]);

  const hint = isDup
    ? 'This photo is already in your closet.'
    : drawMode
      ? 'Drag around the item'
      : atManualCap
        ? `Up to ${MAX_MANUAL_BOXES} drawn items per photo.`
        : current.session.regions.length === 0 && sel.manual.length === 0
          ? 'Nothing detected — draw a box around each item.'
          : 'Tap a box to keep or remove it.';

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-3">
      {/* Stepper */}
      <div className="flex items-center justify-between">
        <button
          type="button"
          onClick={() => goTo(index - 1)}
          disabled={index === 0}
          aria-label="Previous photo"
          className="flex h-9 w-9 items-center justify-center rounded-full disabled:opacity-30"
          style={{ background: 'var(--tr-10)', border: '1px solid var(--tr-20)', color: 'white' }}
        >
          <ChevronLeft size={18} />
        </button>
        <span
          className="font-accent text-[12px] font-semibold uppercase"
          style={{ color: 'rgba(255,255,255,0.6)', letterSpacing: '1px' }}
        >
          Photo {index + 1} of {photos.length}
        </span>
        <button
          type="button"
          onClick={() => goTo(index + 1)}
          disabled={index === photos.length - 1}
          aria-label="Next photo"
          className="flex h-9 w-9 items-center justify-center rounded-full disabled:opacity-30"
          style={{ background: 'var(--tr-10)', border: '1px solid var(--tr-20)', color: 'white' }}
        >
          <ChevronRight size={18} />
        </button>
      </div>

      {/* Photo card */}
      <div
        ref={frameRef}
        className="relative min-h-0 w-full flex-1 overflow-hidden rounded-3xl"
        style={{
          background: '#222',
          border: '1px solid var(--tr-20)',
          boxShadow: '0 20px 40px rgba(0,0,0,0.5)',
          minHeight: 280,
        }}
      >
        <motion.div
          key={index}
          className="absolute inset-0"
          initial={{ opacity: 0, x: 14 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ duration: 0.18, ease: 'easeOut' }}
        >
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={current.previewUrl}
            alt={`Photo ${index + 1}`}
            draggable={false}
            className="absolute inset-0 h-full w-full select-none object-contain"
            style={{ opacity: isDup ? 0.35 : 1 }}
          />

          {isDup ? (
            // Skipped tile — nothing to select here.
            <div className="absolute inset-0 z-20 flex items-center justify-center">
              <span
                className="inline-flex items-center gap-1.5 rounded-full px-3.5 py-2 text-[12.5px] font-semibold text-white"
                style={{
                  background: 'rgba(0,0,0,0.6)',
                  border: '1px solid var(--tr-20)',
                  backdropFilter: 'blur(6px)',
                  WebkitBackdropFilter: 'blur(6px)',
                }}
              >
                <Check size={14} style={{ color: 'var(--mint)' }} /> Already added
              </span>
            </div>
          ) : (
            // Overlay pinned to the CONTAINED image rect — boxes inside are pure %.
            <div className="absolute" style={{ left: ox, top: oy, width: dw, height: dh }}>
              {orderedRegions.map((r, zi) => {
                const [ymin, xmin, ymax, xmax] = r.box_2d;
                const isSel = sel.regionIds.has(r.region_id);
                return (
                  <button
                    key={r.region_id}
                    type="button"
                    onClick={() => toggleRegion(r.region_id)}
                    aria-pressed={isSel}
                    aria-label={`${r.name} region`}
                    className="absolute p-0 text-left transition-opacity duration-150"
                    style={{
                      left: pct(xmin),
                      top: pct(ymin),
                      width: pct(xmax - xmin),
                      height: pct(ymax - ymin),
                      zIndex: 10 + zi, // sorted big→small: smallest area paints on top
                      border: isSel ? '2px solid var(--mint)' : '1.5px dashed rgba(255,255,255,0.35)',
                      background: isSel ? 'rgba(75,226,214,0.10)' : 'transparent',
                      borderRadius: 10,
                      opacity: isSel ? 1 : 0.6,
                      cursor: 'pointer',
                      touchAction: 'manipulation',
                    }}
                  >
                    <BoxLabel name={r.name} />
                    {isSel && (
                      <span
                        aria-hidden
                        className="absolute right-1 top-1 flex h-[18px] w-[18px] items-center justify-center rounded-full"
                        style={{ background: 'var(--mint)', color: 'var(--brand-teal)' }}
                      >
                        <Check size={12} strokeWidth={3} />
                      </span>
                    )}
                  </button>
                );
              })}

              {/* Hand-drawn boxes — always selected; × deletes. */}
              {sel.manual.map((m) => {
                const [ymin, xmin, ymax, xmax] = m.box;
                return (
                  <div
                    key={m.id}
                    className="absolute"
                    style={{
                      left: pct(xmin),
                      top: pct(ymin),
                      width: pct(xmax - xmin),
                      height: pct(ymax - ymin),
                      zIndex: 60,
                      border: '2px solid var(--mint)',
                      background: 'rgba(75,226,214,0.10)',
                      borderRadius: 10,
                    }}
                  >
                    <BoxLabel name="New item" />
                    <button
                      type="button"
                      onClick={() => removeManual(m.id)}
                      aria-label="Remove drawn item"
                      className="absolute flex h-5 w-5 items-center justify-center rounded-full"
                      style={{
                        right: -8,
                        top: -8,
                        background: '#222',
                        border: '1px solid var(--tr-20)',
                        color: 'white',
                        zIndex: 61,
                      }}
                    >
                      <X size={11} />
                    </button>
                  </div>
                );
              })}

              {/* Draw layer — on top of everything while draw mode is active.
                  touch-action:none keeps the page from scrolling mid-drag. */}
              {drawMode && !atManualCap && (
                <div
                  data-testid="draw-layer"
                  className="absolute inset-0 cursor-crosshair"
                  style={{ zIndex: 80, touchAction: 'none' }}
                  onPointerDown={onDrawDown}
                  onPointerMove={onDrawMove}
                  onPointerUp={onDrawUp}
                  onPointerCancel={onDrawCancel}
                >
                  {draft && (
                    <div
                      className="absolute rounded-[10px]"
                      style={{
                        left: draft.x,
                        top: draft.y,
                        width: draft.w,
                        height: draft.h,
                        border: '2px solid var(--mint)',
                        background: 'rgba(75,226,214,0.12)',
                      }}
                    />
                  )}
                </div>
              )}
            </div>
          )}
        </motion.div>
      </div>

      {/* Toolbar: hint + add-missed-region pill */}
      <div className="flex items-center justify-between gap-3">
        <p className="m-0 flex-1 text-[12.5px]" style={{ color: 'rgba(255,255,255,0.6)' }}>
          {hint}
        </p>
        <button
          type="button"
          onClick={() => setDrawMode((d) => !d)}
          disabled={isDup || atManualCap || committing}
          className="inline-flex shrink-0 items-center gap-1.5 rounded-full px-3.5 py-2 text-[13px] font-semibold transition-transform active:scale-95 disabled:opacity-40"
          style={
            drawMode
              ? { background: 'var(--mint)', color: 'var(--brand-teal)', border: '1px solid transparent' }
              : { background: 'var(--tr-10)', border: '1px solid var(--tr-20)', color: 'white' }
          }
        >
          <Plus size={15} /> Add item
        </button>
      </div>

      {/* Footer: selected-count across ALL photos + commit / cancel */}
      <motion.div
        className="flex items-center gap-3"
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.18, ease: 'easeOut' }}
      >
        <button
          type="button"
          onClick={onCancel}
          disabled={committing}
          className="h-[50px] shrink-0 rounded-[10px] px-5 text-[15px] font-medium text-white disabled:opacity-50"
          style={{ background: 'var(--tr-10)', border: '1px solid var(--tr-20)' }}
        >
          Cancel
        </button>
        <DSButton
          className="flex-1"
          loading={committing}
          disabled={totalSelected === 0 || committing}
          onClick={() => onCommit(buildSelections())}
          style={{ background: 'var(--mint)', color: 'var(--brand-teal)' }}
        >
          Add {totalSelected} item{totalSelected === 1 ? '' : 's'}
        </DSButton>
      </motion.div>
    </div>
  );
}
