'use client';

import React, { useEffect } from 'react';
import { motion } from 'framer-motion';
import { Check, CircleAlert, WifiOff } from 'lucide-react';

import { useToastStore, type ToastItem, type ToastTone } from '@/stores/useToastStore';
import { M } from './materials';
import { Spark } from './Spark';

const TONES: Record<ToastTone, { icon: React.ReactNode; bg: string; bd: string; fg: string }> = {
  success: { icon: <Check size={15} />, bg: 'rgba(75,226,214,0.16)', bd: 'rgba(75,226,214,0.4)', fg: 'var(--mint)' },
  error: { icon: <CircleAlert size={15} />, bg: 'rgba(251,44,54,0.16)', bd: 'rgba(251,44,54,0.4)', fg: '#ff8087' },
  info: { icon: <Spark size={13} style={{ color: '#fff' }} />, bg: 'rgba(255,255,255,0.10)', bd: 'rgba(255,255,255,0.2)', fg: '#fff' },
  offline: { icon: <WifiOff size={14} />, bg: 'rgba(240,162,59,0.16)', bd: 'rgba(240,162,59,0.42)', fg: '#f0b566' },
};

/** Single toast — deep glass, toned icon chip, optional mint action. */
export function Toast({ item }: { item: ToastItem }) {
  const dismiss = useToastStore((s) => s.dismiss);
  const t = TONES[item.tone];

  // Auto-dismiss.
  useEffect(() => {
    const timer = window.setTimeout(() => dismiss(item.id), item.duration);
    return () => window.clearTimeout(timer);
  }, [item.id, item.duration, dismiss]);

  return (
    <motion.div
      layout
      drag="x"
      dragConstraints={{ left: 0, right: 0 }}
      dragElastic={0.6}
      onDragEnd={(_e, info) => {
        if (Math.abs(info.offset.x) > 72 || Math.abs(info.velocity.x) > 600) dismiss(item.id);
      }}
      className="pointer-events-auto"
    >
      <div
        role="status"
        data-t2-anim
        className="flex w-full items-center"
        style={{
          ...M.deep(18),
          gap: 11,
          padding: '11px 14px 11px 11px',
          animation: 't2-rise 380ms var(--ease-out) both',
        }}
      >
        <span
          className="flex shrink-0 items-center justify-center"
          style={{
            width: 30,
            height: 30,
            borderRadius: 10,
            background: t.bg,
            border: `1px solid ${t.bd}`,
            color: t.fg,
          }}
          aria-hidden
        >
          {t.icon}
        </span>
        <div className="min-w-0 flex-1">
          <div
            className="overflow-hidden text-ellipsis whitespace-nowrap text-white"
            style={{ fontSize: 13.5, fontWeight: 600, letterSpacing: '-0.1px' }}
          >
            {item.title}
          </div>
          {item.sub && <div style={{ color: M.faint, fontSize: 11.5, marginTop: 1.5 }}>{item.sub}</div>}
        </div>
        {item.action && (
          <button
            type="button"
            className="whitespace-nowrap border-none bg-transparent"
            style={{
              color: 'var(--mint)',
              fontSize: 13,
              fontWeight: 650,
              padding: '4px 6px',
              cursor: 'pointer',
            }}
            onClick={() => {
              item.action?.onClick();
              dismiss(item.id);
            }}
          >
            {item.action.label}
          </button>
        )}
      </div>
    </motion.div>
  );
}

/**
 * §0 · G4 — Toast host. One per app (mounted in AppShell), docked 102px up so
 * it clears the floating nav; `aboveNav={false}` docks it 24px up for
 * nav-less screens. Swipe horizontally to flick a toast away.
 */
export function ToastHost({ aboveNav = true }: { aboveNav?: boolean }) {
  const toasts = useToastStore((s) => s.toasts);
  if (toasts.length === 0) return null;
  return (
    <div
      className="pointer-events-none fixed left-0 right-0 z-[46] mx-auto flex w-full max-w-[430px] flex-col px-5"
      style={{ bottom: aboveNav ? 102 : 24, gap: 8 }}
    >
      {toasts.map((item) => (
        <Toast key={item.id} item={item} />
      ))}
    </div>
  );
}
