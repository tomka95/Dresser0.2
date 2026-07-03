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
import { AlertTriangle, Check, ChevronLeft, ChevronRight, Move, Plus, X } from 'lucide-react';

import type { PhotoCommitSelection, PhotoDetectSession } from '@/lib/api/gmail';
import { logEvent } from '@/lib/api/events';
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
  /** Optional user-given name (blank falls back to the server's auto-describe at commit). */
  name?: string;
}

/** Minimum box size in 0..1000 units when dragging a corner (keeps a grabbable box). */
const MIN_BOX_UNITS = 40;
type DragMode = 'move' | 'nw' | 'ne' | 'sw' | 'se';

interface PhotoSelection {
  regionIds: Set<number>;
  manual: ManualBox[];
  /** Detected region ids converted to editable manual boxes (hidden as detected boxes). */
  adjusted: Set<number>;
}

const MAX_MANUAL_BOXES = 8;
/** Minimum drag size (fraction of the displayed image per dimension) to keep a drawn box. */
const MIN_DRAW_FRACTION = 0.04;

const pct = (v: number) => `${v / 10}%`; // 0..1000 → CSS %
const boxArea = ([ymin, xmin, ymax, xmax]: Box) =>
  Math.max(0, ymax - ymin) * Math.max(0, xmax - xmin);
const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));

// ── Occlusion / size guard (cheap, no model) ────────────────────────────────
// A garment crop is only useful if it's big enough AND mostly visible. Two signals,
// both from box geometry alone:
//   • area  — the box covers less than this fraction of the whole photo → too small a
//     scrap to be a usable garment crop (the white-tee-sliver case).
//   • cover — this fraction (or more) of the box is overlapped by a LARGER kept box →
//     the item is mostly hidden behind another, so its crop is mostly the other garment.
const MIN_USABLE_AREA_FRAC = 0.02;   // 2% of the photo (0..1000² units)
const OCCLUDED_COVER_FRAC = 0.7;     // 70% of this box covered by a bigger one
const PHOTO_AREA = 1000 * 1000;

/** Fraction of box `a` overlapped by box `b` (0..1). */
function coveredFraction(a: Box, b: Box): number {
  const iy = Math.max(0, Math.min(a[2], b[2]) - Math.max(a[0], b[0]));
  const ix = Math.max(0, Math.min(a[3], b[3]) - Math.max(a[1], b[1]));
  const inter = iy * ix;
  const area = boxArea(a);
  return area > 0 ? inter / area : 0;
}

/** A non-blocking warning for a kept box, or null. `others` are the other kept boxes. */
function occlusionWarning(box: Box, others: Box[]): string | null {
  if (boxArea(box) / PHOTO_AREA < MIN_USABLE_AREA_FRAC) {
    return 'Very small — may be too little to identify';
  }
  const selfArea = boxArea(box);
  for (const o of others) {
    // Only a LARGER box can plausibly occlude this one.
    if (boxArea(o) > selfArea && coveredFraction(box, o) >= OCCLUDED_COVER_FRAC) {
      return 'Mostly hidden behind another item';
    }
  }
  return null;
}

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

/** Subtle amber occlusion/size warning chip at a box's bottom-left. Non-blocking. */
function WarnBadge({ text }: { text: string }) {
  return (
    <span
      title={text}
      className="absolute bottom-1 left-1 z-[3] inline-flex max-w-[92%] items-center gap-1 truncate rounded-md px-1.5 py-0.5 text-[9.5px] font-semibold"
      style={{
        background: 'rgba(245,158,11,0.92)',
        color: '#3a2400',
      }}
    >
      <AlertTriangle size={10} strokeWidth={2.6} className="shrink-0" />
      {text}
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
      adjusted: new Set<number>(),
    })),
  );

  const [drawMode, setDrawMode] = useState(false);
  // Live rubber-band rect while drawing, in px relative to the displayed image rect.
  const [draft, setDraft] = useState<{ x: number; y: number; w: number; h: number } | null>(null);
  const drawStartRef = useRef<{ x: number; y: number } | null>(null);
  const manualSeqRef = useRef(0);
  // Active move/resize drag on a manual box (px start + the box at grab time).
  const boxDragRef = useRef<{ id: number; mode: DragMode; sx: number; sy: number; box: Box } | null>(null);

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

  // Occlusion/size guard for the CURRENT photo's KEPT boxes (selected detected regions
  // that aren't being adjusted + all manual boxes). Non-blocking — surfaces a subtle
  // warning; the user can still commit.
  const occWarnings = useMemo(() => {
    const kept: { kind: 'det' | 'man'; id: number; box: Box }[] = [];
    for (const r of current.session.regions) {
      if (sel.regionIds.has(r.region_id) && !sel.adjusted.has(r.region_id)) {
        kept.push({ kind: 'det', id: r.region_id, box: r.box_2d as Box });
      }
    }
    for (const m of sel.manual) kept.push({ kind: 'man', id: m.id, box: m.box });

    const det: Record<number, string> = {};
    const man: Record<number, string> = {};
    let count = 0;
    kept.forEach((k, ki) => {
      const others = kept.filter((_, oi) => oi !== ki).map((o) => o.box);
      const w = occlusionWarning(k.box, others);
      if (!w) return;
      count += 1;
      if (k.kind === 'det') det[k.id] = w;
      else man[k.id] = w;
    });
    return { det, man, count };
  }, [current.session, sel]);

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

  const renameManual = useCallback(
    (id: number, name: string) => {
      setSelections((prev) =>
        prev.map((s, i) =>
          i === index ? { ...s, manual: s.manual.map((m) => (m.id === id ? { ...m, name } : m)) } : s,
        ),
      );
    },
    [index],
  );

  // "Adjust" a detected box: turn it into an editable (drag/resize/name) manual box so the
  // ADJUSTED geometry flows to the cutout. The detected region is deselected and re-added
  // as a manual box seeded with its geometry + name. (Manual boxes are box→cutout, no mask.)
  const adjustRegion = useCallback(
    (regionId: number, box: Box, name: string) => {
      if (committing) return;
      setSelections((prev) =>
        prev.map((s, i) => {
          if (i !== index) return s;
          if (s.manual.length >= MAX_MANUAL_BOXES) return s;
          const regionIds = new Set(s.regionIds);
          regionIds.delete(regionId);
          const adjusted = new Set(s.adjusted);
          adjusted.add(regionId);
          return {
            ...s,
            regionIds,
            adjusted,
            manual: [...s.manual, { id: ++manualSeqRef.current, box: [...box] as Box, name }],
          };
        }),
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

  // ── Move / resize a manual box (per-element pointer capture) ────────────────
  // px deltas → 0..1000 units via the displayed image size (dw/dh). Move keeps the box
  // size and clamps to the image; each corner handle resizes that corner (min size kept).
  const beginBoxDrag = (e: React.PointerEvent, id: number, mode: DragMode, box: Box) => {
    if (committing) return;
    e.stopPropagation();
    boxDragRef.current = { id, mode, sx: e.clientX, sy: e.clientY, box: [...box] as Box };
    e.currentTarget.setPointerCapture?.(e.pointerId);
  };

  const moveBoxDrag = (e: React.PointerEvent) => {
    const d = boxDragRef.current;
    if (!d || dw <= 0 || dh <= 0) return;
    const dxu = ((e.clientX - d.sx) / dw) * 1000;
    const dyu = ((e.clientY - d.sy) / dh) * 1000;
    let [ymin, xmin, ymax, xmax] = d.box;
    if (d.mode === 'move') {
      const w = xmax - xmin;
      const h = ymax - ymin;
      const nx = clamp(xmin + dxu, 0, 1000 - w);
      const ny = clamp(ymin + dyu, 0, 1000 - h);
      xmin = nx;
      xmax = nx + w;
      ymin = ny;
      ymax = ny + h;
    } else {
      if (d.mode.includes('n')) ymin = clamp(ymin + dyu, 0, ymax - MIN_BOX_UNITS);
      if (d.mode.includes('s')) ymax = clamp(ymax + dyu, ymin + MIN_BOX_UNITS, 1000);
      if (d.mode.includes('w')) xmin = clamp(xmin + dxu, 0, xmax - MIN_BOX_UNITS);
      if (d.mode.includes('e')) xmax = clamp(xmax + dxu, xmin + MIN_BOX_UNITS, 1000);
    }
    const nb: Box = [Math.round(ymin), Math.round(xmin), Math.round(ymax), Math.round(xmax)];
    setSelections((prev) =>
      prev.map((s, i) =>
        i === index ? { ...s, manual: s.manual.map((m) => (m.id === d.id ? { ...m, box: nb } : m)) } : s,
      ),
    );
  };

  const endBoxDrag = () => {
    boxDragRef.current = null;
  };

  const boxDragProps = (id: number, mode: DragMode, box: Box) => ({
    onPointerDown: (e: React.PointerEvent) => beginBoxDrag(e, id, mode, box),
    onPointerMove: moveBoxDrag,
    onPointerUp: endBoxDrag,
    onPointerCancel: endBoxDrag,
  });

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
          // Carry the user's name through when they gave one; a blank name falls back to
          // the server's auto-describe (bare geometry).
          manual_boxes: chosen.manual.map((m) => {
            const nm = m.name?.trim();
            return nm ? { box: m.box, name: nm } : m.box;
          }),
        },
      ];
    });
  }, [photos, selections]);

  // Occlusion warnings take priority in the hint (still non-blocking) so the user knows
  // why a box is flagged; commit stays enabled.
  const occHint =
    occWarnings.count > 0 && !drawMode && !isDup
      ? occWarnings.count === 1
        ? 'One item looks small or mostly hidden — you can still add it.'
        : `${occWarnings.count} items look small or mostly hidden — you can still add them.`
      : null;

  const hint = isDup
    ? 'This photo is already in your closet.'
    : drawMode
      ? 'Drag around the item'
      : occHint
        ? occHint
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
                // Converted to a manual box → hide the detected one (the manual box shows).
                if (sel.adjusted.has(r.region_id)) return null;
                const [ymin, xmin, ymax, xmax] = r.box_2d;
                const isSel = sel.regionIds.has(r.region_id);
                return (
                  // Wrapper (no nested buttons): a fill toggle + a corner "adjust" control.
                  <div
                    key={r.region_id}
                    className="absolute"
                    style={{
                      left: pct(xmin),
                      top: pct(ymin),
                      width: pct(xmax - xmin),
                      height: pct(ymax - ymin),
                      zIndex: 10 + zi, // sorted big→small: smallest area paints on top
                    }}
                  >
                    <button
                      type="button"
                      onClick={() => {
                        logEvent({
                          eventType: 'region_select',
                          entityType: 'photo_detect_session',
                          entityId: current.session.session_id ?? undefined,
                          source: 'photo',
                          properties: { mode: 'detected', region_id: r.region_id, selected: !isSel },
                        });
                        toggleRegion(r.region_id);
                      }}
                      aria-pressed={isSel}
                      aria-label={`${r.name} region`}
                      className="absolute inset-0 p-0 text-left transition-opacity duration-150"
                      style={{
                        border: isSel ? '2px solid var(--mint)' : '1.5px dashed rgba(255,255,255,0.35)',
                        background: isSel ? 'rgba(75,226,214,0.10)' : 'transparent',
                        borderRadius: 10,
                        opacity: isSel ? 1 : 0.6,
                        cursor: 'pointer',
                        touchAction: 'manipulation',
                      }}
                    >
                      <BoxLabel name={r.name} />
                      {isSel && occWarnings.det[r.region_id] && (
                        <WarnBadge text={occWarnings.det[r.region_id]} />
                      )}
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
                    {/* Adjust → convert this detected box into an editable manual box. */}
                    {isSel && !committing && (
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation();
                          adjustRegion(r.region_id, r.box_2d, r.name);
                        }}
                        aria-label={`Adjust ${r.name} box`}
                        className="absolute flex h-6 w-6 items-center justify-center rounded-full active:scale-90"
                        style={{
                          right: -9,
                          bottom: -9,
                          background: '#222',
                          border: '1px solid var(--tr-20)',
                          color: 'white',
                          zIndex: 2,
                        }}
                      >
                        <Move size={12} />
                      </button>
                    )}
                  </div>
                );
              })}

              {/* Hand-drawn / adjusted boxes — always selected. Drag body to move, corner
                  handles to resize, inline input to name; × deletes. */}
              {sel.manual.map((m) => {
                const [ymin, xmin, ymax, xmax] = m.box;
                return (
                  <div
                    key={m.id}
                    className="absolute"
                    {...boxDragProps(m.id, 'move', m.box)}
                    style={{
                      left: pct(xmin),
                      top: pct(ymin),
                      width: pct(xmax - xmin),
                      height: pct(ymax - ymin),
                      zIndex: 60,
                      border: '2px solid var(--mint)',
                      background: 'rgba(75,226,214,0.10)',
                      borderRadius: 10,
                      touchAction: 'none',
                      cursor: committing ? 'default' : 'move',
                    }}
                  >
                    {/* Optional name — blank falls back to the server's auto-describe. */}
                    <input
                      value={m.name ?? ''}
                      onChange={(e) => renameManual(m.id, e.target.value)}
                      placeholder="Name (optional)"
                      disabled={committing}
                      onPointerDown={(e) => e.stopPropagation()}
                      onClick={(e) => e.stopPropagation()}
                      className="absolute left-1 top-1 w-[74%] truncate rounded-md px-1.5 py-0.5 text-[10px] font-medium text-white outline-none placeholder:text-white/45"
                      style={{ background: 'rgba(0,0,0,0.55)', border: '1px solid var(--tr-20)' }}
                    />
                    {occWarnings.man[m.id] && <WarnBadge text={occWarnings.man[m.id]} />}
                    <button
                      type="button"
                      onPointerDown={(e) => e.stopPropagation()}
                      onClick={(e) => {
                        e.stopPropagation();
                        removeManual(m.id);
                      }}
                      aria-label="Remove drawn item"
                      className="absolute flex h-5 w-5 items-center justify-center rounded-full"
                      style={{
                        right: -8,
                        top: -8,
                        background: '#222',
                        border: '1px solid var(--tr-20)',
                        color: 'white',
                        zIndex: 62,
                      }}
                    >
                      <X size={11} />
                    </button>
                    {/* Corner resize handles. */}
                    {!committing &&
                      (['nw', 'ne', 'sw', 'se'] as const).map((h) => (
                        <span
                          key={h}
                          {...boxDragProps(m.id, h, m.box)}
                          aria-hidden
                          className="absolute h-3.5 w-3.5 rounded-full"
                          style={{
                            ...(h === 'nw'
                              ? { left: -7, top: -7, cursor: 'nwse-resize' }
                              : h === 'ne'
                                ? { right: -7, top: -7, cursor: 'nesw-resize' }
                                : h === 'sw'
                                  ? { left: -7, bottom: -7, cursor: 'nesw-resize' }
                                  : { right: -7, bottom: -7, cursor: 'nwse-resize' }),
                            background: 'var(--mint)',
                            border: '2px solid #222',
                            zIndex: 62,
                            touchAction: 'none',
                          }}
                        />
                      ))}
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
        <p
          className="m-0 flex-1 text-[12.5px]"
          style={{ color: occHint ? 'var(--amber, #f59e0b)' : 'rgba(255,255,255,0.6)' }}
        >
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
