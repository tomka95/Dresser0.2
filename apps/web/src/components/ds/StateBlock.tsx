'use client';

import React from 'react';
import Link from 'next/link';
import {
  Camera,
  Check,
  CircleAlert,
  CloudOff,
  FileX,
  Hourglass,
  Image as ImageIcon,
  Mail,
  MapPin,
  RotateCw,
  WifiOff,
} from 'lucide-react';

import { Btn } from './Button';
import { M } from './materials';

/* ══════════════════════════════════════════════════════════════════════════
   §0 · G9 — One anatomy for every empty / error / offline / permission state:
   medallion → title → one calm line → actions → reassurance footnote.
   ══════════════════════════════════════════════════════════════════════════ */

export type MedallionTone = 'plain' | 'mint' | 'danger' | 'amber';

const MEDALLION_TONES: Record<MedallionTone, { fg: string; bd: string; glow: string }> = {
  plain: { fg: 'rgba(255,255,255,0.85)', bd: 'rgba(255,255,255,0.16)', glow: 'transparent' },
  mint: { fg: 'var(--mint)', bd: 'rgba(75,226,214,0.4)', glow: 'rgba(75,226,214,0.22)' },
  danger: { fg: '#ff8087', bd: 'rgba(251,44,54,0.4)', glow: 'rgba(251,44,54,0.16)' },
  amber: { fg: '#f0b566', bd: 'rgba(240,162,59,0.45)', glow: 'rgba(240,162,59,0.16)' },
};

export interface MedallionProps {
  icon?: React.ReactNode;
  tone?: MedallionTone;
  size?: number;
  /** Slow pulsing ring around the disc. */
  pulse?: boolean;
}

/** Glass disc — the shared visual anchor for every state template. */
export function Medallion({ icon, tone = 'plain', size = 84, pulse = false }: MedallionProps) {
  const t = MEDALLION_TONES[tone];
  return (
    <div className="relative shrink-0" style={{ width: size, height: size }}>
      {pulse && (
        <span
          data-t2-anim
          className="absolute rounded-full"
          style={{
            inset: -7,
            border: `1.5px solid ${t.bd}`,
            animation: 't2-ring 2.2s ease-out infinite',
          }}
          aria-hidden
        />
      )}
      <div
        className="absolute inset-0 flex items-center justify-center rounded-full"
        style={{
          background: 'radial-gradient(circle at 35% 28%, rgba(255,255,255,0.13), rgba(255,255,255,0.04))',
          border: `1px solid ${t.bd}`,
          boxShadow: `inset 0 1px 0 rgba(255,255,255,0.14), 0 14px 34px -10px rgba(0,0,0,0.5), 0 0 30px ${t.glow}`,
          backdropFilter: 'blur(14px)',
          WebkitBackdropFilter: 'blur(14px)',
          color: t.fg,
        }}
      >
        {icon}
      </div>
    </div>
  );
}

export interface StateBlockProps {
  icon?: React.ReactNode;
  tone?: MedallionTone;
  title: string;
  sub?: string;
  /** Primary action (a <Btn>). */
  cta?: React.ReactNode;
  /** Quiet alternative under the primary. */
  cta2?: React.ReactNode;
  /** Reassurance footnote (11.5px, ghost). */
  foot?: string;
  pulse?: boolean;
  children?: React.ReactNode;
  /** Tighter paddings + 68px medallion for inline use. */
  compact?: boolean;
}

export function StateBlock({
  icon,
  tone,
  title,
  sub,
  cta,
  cta2,
  foot,
  pulse,
  children,
  compact = false,
}: StateBlockProps) {
  return (
    <div
      className="flex flex-col items-center text-center"
      style={{ padding: compact ? '26px 22px' : '40px 28px' }}
    >
      <Medallion icon={icon} tone={tone} pulse={pulse} size={compact ? 68 : 84} />
      <div
        style={{
          color: '#fff',
          fontSize: compact ? 16 : 18,
          fontWeight: 650,
          letterSpacing: '-0.35px',
          marginTop: 20,
        }}
      >
        {title}
      </div>
      {sub && (
        <div style={{ color: M.faint, fontSize: 13.5, lineHeight: 1.55, marginTop: 7, maxWidth: 248 }}>
          {sub}
        </div>
      )}
      {children}
      {(cta || cta2) && (
        <div
          className="flex flex-col items-stretch"
          style={{ gap: 9, marginTop: 22, width: compact ? 'auto' : '100%', maxWidth: 250 }}
        >
          {cta}
          {cta2}
        </div>
      )}
      {foot && <div style={{ color: M.ghost, fontSize: 11.5, marginTop: 16 }}>{foot}</div>}
    </div>
  );
}

/** Full-height centered version for whole-screen states. */
export function StateScreen(props: StateBlockProps) {
  return (
    <div className="absolute inset-0 flex items-center justify-center" style={{ padding: '54px 0' }}>
      <StateBlock {...props} />
    </div>
  );
}

/* ── Canned states ───────────────────────────────────────────────────────── */

export function ErrorState({
  title = 'Something went wrong',
  sub = 'We couldn’t load this. Your closet is safe.',
  onRetry,
  retryLabel = 'Try again',
  compact,
}: {
  title?: string;
  sub?: string;
  onRetry?: () => void;
  retryLabel?: string;
  compact?: boolean;
}) {
  return (
    <StateBlock
      compact={compact}
      tone="danger"
      icon={<CircleAlert size={30} />}
      title={title}
      sub={sub}
      cta={
        <Btn variant="glass" size="md" icon={<RotateCw size={16} />} onClick={onRetry}>
          {retryLabel}
        </Btn>
      }
    />
  );
}

/** Amber pill — "you're offline" strip. Positioning is the caller's job. */
export function OfflineBanner({ style, className }: { style?: React.CSSProperties; className?: string }) {
  return (
    <div
      role="status"
      className={className}
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 8,
        padding: '8px 14px',
        borderRadius: 999,
        background: 'rgba(240,162,59,0.14)',
        border: '1px solid rgba(240,162,59,0.35)',
        backdropFilter: 'blur(14px)',
        WebkitBackdropFilter: 'blur(14px)',
        color: '#f0b566',
        fontSize: 12,
        fontWeight: 600,
        width: 'fit-content',
        margin: '0 auto',
        ...style,
      }}
    >
      <WifiOff size={14} /> You&rsquo;re offline &mdash; showing your saved closet
    </div>
  );
}

export function OfflineScreen({
  context = 'Your closet is saved on this phone — outfits and chat need a connection.',
  onRetry,
  onBrowseCloset,
}: {
  context?: string;
  onRetry?: () => void;
  onBrowseCloset?: () => void;
}) {
  return (
    <StateScreen
      tone="amber"
      pulse
      icon={<CloudOff size={32} />}
      title="No connection"
      sub={context}
      cta={
        <Btn variant="glass" size="md" icon={<RotateCw size={16} />} onClick={onRetry}>
          Retry
        </Btn>
      }
      cta2={
        <Btn variant="ghost" size="md" onClick={onBrowseCloset}>
          Browse offline closet
        </Btn>
      }
    />
  );
}

export type PermissionKind = 'camera' | 'photos' | 'location' | 'gmail';

const PERMISSION_COPY: Record<PermissionKind, { icon: React.ReactNode; title: string; sub: string }> = {
  camera: {
    icon: <Camera size={30} />,
    title: 'Camera access is off',
    sub: 'Tailor uses the camera to snap items into your closet. Nothing is stored without you confirming.',
  },
  photos: {
    icon: <ImageIcon size={30} />,
    title: 'Photo access is off',
    sub: 'Allow photo access to pull clothes from your camera roll. You pick every photo — nothing is scanned in the background.',
  },
  location: {
    icon: <MapPin size={30} />,
    title: 'Location is off',
    sub: 'Weather-aware outfits use your rough location, once a day. You can type a city instead.',
  },
  gmail: {
    icon: <Mail size={30} />,
    title: 'Gmail permission declined',
    sub: 'Tailor only reads order receipts — never personal mail. You can grant read-only access in the next step.',
  },
};

export function PermissionState({
  kind = 'camera',
  onOpenSettings,
  onSecondary,
  compact,
}: {
  kind?: PermissionKind;
  onOpenSettings?: () => void;
  /** "Not now" (or "Enter city manually" for location). */
  onSecondary?: () => void;
  compact?: boolean;
}) {
  const s = PERMISSION_COPY[kind];
  return (
    <StateBlock
      compact={compact}
      tone="amber"
      icon={s.icon}
      title={s.title}
      sub={s.sub}
      cta={
        <Btn variant="primary" size="md" onClick={onOpenSettings}>
          Open Settings
        </Btn>
      }
      cta2={
        <Btn variant="ghost" size="md" onClick={onSecondary}>
          {kind === 'location' ? 'Enter city manually' : 'Not now'}
        </Btn>
      }
    />
  );
}

export function RateLimitState({
  title = 'You’ve hit today’s limit',
  sub = 'Styling requests refresh every morning. Yours resets in',
  reset,
  onBrowseCloset,
  compact,
}: {
  title?: string;
  sub?: string;
  /** Countdown chip content — a formatted string or a live countdown node. */
  reset?: React.ReactNode;
  onBrowseCloset?: () => void;
  compact?: boolean;
}) {
  return (
    <StateBlock
      compact={compact}
      tone="amber"
      icon={<Hourglass size={30} />}
      title={title}
      sub={sub}
      cta={
        <Btn variant="ghost" size="md" onClick={onBrowseCloset}>
          Browse your closet meanwhile
        </Btn>
      }
    >
      {reset != null && (
        <span
          className="inline-flex items-center"
          style={{
            marginTop: 13,
            gap: 7,
            padding: '7px 15px',
            borderRadius: 999,
            background: 'rgba(255,255,255,0.08)',
            border: '1px solid rgba(255,255,255,0.14)',
            color: '#fff',
            fontSize: 13.5,
            fontWeight: 650,
            fontVariantNumeric: 'tabular-nums',
          }}
        >
          <Hourglass size={14} style={{ color: '#f0b566' }} /> {reset}
        </span>
      )}
    </StateBlock>
  );
}

export function NotFoundState() {
  return (
    <StateScreen
      icon={
        /* eslint-disable-next-line @next/next/no-img-element */
        <img
          src="/9.png"
          alt=""
          style={{ width: 38, opacity: 0.85, filter: 'brightness(3) grayscale(1)' }}
          aria-hidden
        />
      }
      title="This rack is empty"
      sub="The page you're after was moved, or never hung here."
      cta={
        <Link href="/home" className="flex flex-col items-stretch">
          <Btn variant="primary" size="md" fullWidth>
            Back to Home
          </Btn>
        </Link>
      }
      foot="404 — page not found"
    />
  );
}

export function CrashScreen({
  onReload,
  onReport,
  errorRef,
}: {
  /** Wire to Next's error-boundary reset(); defaults to a hard reload. */
  onReload?: () => void;
  /** When absent the report button renders disabled ("reporting coming soon"). */
  onReport?: () => void;
  /** Error digest/reference shown in the footnote. */
  errorRef?: string;
}) {
  return (
    <StateScreen
      tone="danger"
      icon={<FileX size={30} />}
      title="Well, this wasn't tailored"
      sub="The app hit a snag it couldn't recover from. Your closet and chats are safe."
      cta={
        <Btn
          variant="primary"
          size="md"
          icon={<RotateCw size={16} />}
          onClick={onReload ?? (() => window.location.reload())}
        >
          Reload Tailor
        </Btn>
      }
      cta2={
        <Btn
          variant="ghost"
          size="md"
          onClick={onReport}
          disabled={!onReport}
          title={onReport ? undefined : 'Reporting coming soon'}
        >
          Report the issue
        </Btn>
      }
      foot={errorRef ? `Error ref ${errorRef} · nothing was lost` : 'Nothing was lost'}
    />
  );
}

/** One-shot celebration medallion (pop + pulse). */
export function SuccessPop({ size = 92 }: { size?: number }) {
  return (
    <div data-t2-anim style={{ animation: 't2-pop 600ms var(--ease-out) both' }}>
      <Medallion tone="mint" pulse size={size} icon={<Check size={Math.round(size * 0.38)} />} />
    </div>
  );
}
