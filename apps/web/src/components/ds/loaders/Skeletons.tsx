import React from 'react';
import { cn } from '@/lib/utils';

/* ══════════════════════════════════════════════════════════════════════════
   §0 · G5 — Skeleton library. One shimmer (.t2-sk in globals.css): a 1.8s
   light sweep over 5.5%-white blocks, radii matched to the component they
   stand in for. The mint sweep is reserved for AI surfaces.
   ══════════════════════════════════════════════════════════════════════════ */

export interface SkProps {
  w?: number | string;
  h?: number | string;
  r?: number | string;
  /** Mint sweep — AI surfaces only. */
  mint?: boolean;
  style?: React.CSSProperties;
  className?: string;
}

/** Base shimmer block. */
export function Sk({ w = '100%', h = 14, r = 8, mint = false, style, className }: SkProps) {
  return (
    <div
      className={cn('t2-sk', mint && 't2-sk-mint', className)}
      style={{ width: w, height: h, borderRadius: r, ...style }}
      aria-hidden
    />
  );
}

export function SkCircle({ d = 40, style }: { d?: number; style?: React.CSSProperties }) {
  return <Sk w={d} h={d} r="50%" style={style} />;
}

/** 3:4 tile — closet/lookbook cards. */
export function SkTile({ h, style }: { h?: number; style?: React.CSSProperties }) {
  return (
    <div
      className="t2-sk"
      style={{
        borderRadius: 20,
        aspectRatio: h ? undefined : '3 / 4',
        height: h,
        border: '1px solid rgba(255,255,255,0.06)',
        ...style,
      }}
      aria-hidden
    />
  );
}

/** Grid — closet, lookbook. */
export function SkGrid({ rows = 2 }: { rows?: number }) {
  return (
    <div className="grid grid-cols-2 gap-3">
      {Array.from({ length: rows * 2 }).map((_, i) => (
        <div key={i}>
          <SkTile />
          <Sk w="70%" h={11} style={{ marginTop: 9 }} />
          <Sk w="42%" h={9} style={{ marginTop: 6 }} />
        </div>
      ))}
    </div>
  );
}

/** List — search, history. */
export function SkList({ n = 3 }: { n?: number }) {
  return (
    <div className="flex flex-col" style={{ gap: 11 }}>
      {Array.from({ length: n }).map((_, i) => (
        <div
          key={i}
          className="flex items-center gap-3"
          style={{
            padding: '12px 14px',
            borderRadius: 18,
            background: 'rgba(255,255,255,0.045)',
            border: '1px solid rgba(255,255,255,0.07)',
          }}
        >
          <Sk w={52} h={62} r={12} />
          <div className="flex-1">
            <Sk w="58%" h={12} />
            <Sk w="34%" h={9} style={{ marginTop: 8 }} />
          </div>
          <SkCircle d={26} />
        </div>
      ))}
    </div>
  );
}

/** Detail — item, product. */
export function SkDetail() {
  return (
    <div>
      <Sk h={300} r={26} />
      <Sk w="52%" h={20} style={{ marginTop: 18 }} />
      <Sk w="30%" h={12} style={{ marginTop: 10 }} />
      <div className="flex flex-col" style={{ marginTop: 18, gap: 10 }}>
        {[0, 1, 2, 3].map((i) => (
          <div key={i} className="flex justify-between gap-3">
            <Sk w="28%" h={12} />
            <Sk w="38%" h={12} />
          </div>
        ))}
      </div>
    </div>
  );
}

/** Chat — stylist thread. */
export function SkChat() {
  const Bubble = ({ me, w1, w2 }: { me?: boolean; w1: string; w2: string }) => (
    <div className={cn('flex', me ? 'justify-end' : 'justify-start')}>
      <div
        style={{
          width: '68%',
          padding: '13px 15px',
          borderRadius: me ? '20px 20px 6px 20px' : '20px 20px 20px 6px',
          background: 'rgba(255,255,255,0.05)',
          border: '1px solid rgba(255,255,255,0.07)',
        }}
      >
        <Sk w={w1} h={10} />
        <Sk w={w2} h={10} style={{ marginTop: 7 }} />
      </div>
    </div>
  );
  return (
    <div className="flex flex-col gap-3">
      <Bubble w1="88%" w2="55%" />
      <Bubble me w1="70%" w2="40%" />
      <Bubble w1="92%" w2="66%" />
    </div>
  );
}

/** Feed — home bento. */
export function SkFeed() {
  return (
    <div className="flex flex-col" style={{ gap: 13 }}>
      <div className="flex gap-3">
        <Sk h={118} r={24} style={{ flex: 1.3 }} />
        <Sk h={118} r={24} style={{ flex: 1 }} />
      </div>
      <Sk h={148} r={24} mint />
      <div className="flex gap-3">
        <SkTile style={{ flex: 1 }} />
        <SkTile style={{ flex: 1 }} />
      </div>
    </div>
  );
}
