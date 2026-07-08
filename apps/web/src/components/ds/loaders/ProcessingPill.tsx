'use client';

import React from 'react';
import { Check, CircleAlert, X } from 'lucide-react';

import { M } from '../materials';
import { Thinking } from './LottieMark';

export type ProcessingState = 'running' | 'done' | 'error' | 'provisional';

export interface ProcessingPillProps {
  label?: string;
  /** 0..1 — ignored when state is 'provisional' (indeterminate sweep). */
  progress?: number;
  state?: ProcessingState;
  /** 52px disc form with a mint activity dot. */
  minimized?: boolean;
  /** Close/dismiss (running form). */
  onDismiss?: () => void;
  /** Tap handler (retry on error, expand when minimized). */
  onClick?: () => void;
  style?: React.CSSProperties;
}

/**
 * §0 · I6 — "Tailoring…" background-ingest status pill. Deep-glass pill that
 * persists across tabs: running (progress bar), provisional (indeterminate
 * sweep), done (mint glow + "Added to your closet"), error ("tap to retry"),
 * or minimized to a 52px disc.
 */
export function ProcessingPill({
  label = 'Tailoring 3 items…',
  progress = 0.55,
  state = 'running',
  minimized = false,
  onDismiss,
  onClick,
  style,
}: ProcessingPillProps) {
  const done = state === 'done';
  const error = state === 'error';
  const provisional = state === 'provisional';

  if (minimized) {
    // Presentational disc only — NO interactive <button> here. The pill is always
    // wrapped by an interactive parent (BackgroundTailorNotice's motion.button, which
    // owns onClick + aria-label); a nested <button> is invalid HTML and triggers a
    // hydration error ("<button> cannot be a descendant of <button>").
    return (
      <span
        role="img"
        aria-label={label}
        onClick={onClick}
        className="relative flex items-center justify-center"
        style={{ ...M.deep(999), width: 52, height: 52, ...style }}
      >
        <Thinking size={30} />
        <span
          className="absolute rounded-full"
          style={{
            top: 3,
            right: 3,
            width: 9,
            height: 9,
            background: 'var(--mint)',
            border: '2px solid #0b1716',
          }}
          aria-hidden
        />
      </span>
    );
  }

  return (
    <div
      role="status"
      onClick={error ? onClick : undefined}
      className="inline-flex items-center"
      style={{
        ...M.deep(999),
        gap: 11,
        padding: '8px 16px 8px 9px',
        boxShadow: done
          ? '0 0 26px rgba(75,226,214,0.3), 0 16px 40px -10px rgba(0,0,0,0.6)'
          : M.deep().boxShadow,
        border: done
          ? '1px solid rgba(75,226,214,0.45)'
          : error
            ? '1px solid rgba(251,44,54,0.4)'
            : M.deep().border,
        cursor: error ? 'pointer' : undefined,
        ...style,
      }}
    >
      {done ? (
        <span
          className="flex items-center justify-center rounded-full"
          style={{ width: 32, height: 32, background: 'rgba(75,226,214,0.15)', color: 'var(--mint)' }}
          aria-hidden
        >
          <Check size={17} />
        </span>
      ) : error ? (
        <span
          className="flex items-center justify-center rounded-full"
          style={{ width: 32, height: 32, background: 'rgba(251,44,54,0.14)', color: '#ff8087' }}
          aria-hidden
        >
          <CircleAlert size={17} />
        </span>
      ) : (
        <Thinking size={32} />
      )}
      <div style={{ minWidth: 128 }}>
        <div
          className="whitespace-nowrap text-white"
          style={{ fontSize: 12.8, fontWeight: 600, letterSpacing: '-0.1px' }}
        >
          {label}
        </div>
        {!done && !error && (
          <div
            className="relative overflow-hidden"
            style={{ marginTop: 5, height: 3.5, borderRadius: 2, background: 'rgba(255,255,255,0.12)' }}
          >
            {provisional ? (
              <span
                data-t2-anim
                className="absolute bottom-0 top-0"
                style={{
                  width: '38%',
                  borderRadius: 2,
                  background: 'linear-gradient(90deg, transparent, var(--mint), transparent)',
                  animation: 't2-bar 1.6s var(--ease-in-out) infinite',
                }}
              />
            ) : (
              <span
                className="block h-full"
                style={{
                  width: `${Math.max(0, Math.min(1, progress)) * 100}%`,
                  borderRadius: 2,
                  background: 'linear-gradient(90deg, #147f74, var(--mint))',
                  transition: 'width 400ms var(--ease-out)',
                }}
              />
            )}
          </div>
        )}
        {done && <div style={{ color: 'var(--mint)', fontSize: 11, marginTop: 1 }}>Added to your closet</div>}
        {error && <div style={{ color: '#ff9096', fontSize: 11, marginTop: 1 }}>Failed — tap to retry</div>}
      </div>
      {!done && !error && onDismiss && (
        <button
          type="button"
          aria-label="Dismiss"
          onClick={onDismiss}
          className="flex border-none bg-transparent"
          style={{ color: M.ghost, cursor: 'pointer', padding: 0 }}
        >
          <X size={15} />
        </button>
      )}
    </div>
  );
}
