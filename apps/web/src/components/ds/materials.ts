import type { CSSProperties } from 'react';

/**
 * Tailor material ladder — the four glass/teal surfaces every §0+ screen
 * composes, plus the shared text alphas and the press spring. Factories return
 * plain style objects so they can be spread into inline styles:
 *
 *   <div style={{ ...M.deep(999), height: 64 }} />
 */
export const M = {
  /** frost — light glass card on photo */
  glass: (r: number = 24): CSSProperties => ({
    borderRadius: r,
    background: 'linear-gradient(165deg, rgba(255,255,255,0.115), rgba(255,255,255,0.05))',
    border: '1px solid rgba(255,255,255,0.14)',
    boxShadow: 'inset 0 1px 0 rgba(255,255,255,0.10), 0 12px 32px -8px rgba(0,0,0,0.42)',
    backdropFilter: 'blur(22px) saturate(150%)',
    WebkitBackdropFilter: 'blur(22px) saturate(150%)',
  }),
  /** deep — teal-black glass: nav, sheets, dialogs, toasts */
  deep: (r: number = 28): CSSProperties => ({
    borderRadius: r,
    background: 'linear-gradient(180deg, rgba(16,32,31,0.82), rgba(9,20,20,0.88))',
    border: '1px solid rgba(255,255,255,0.12)',
    boxShadow: 'inset 0 1px 0 rgba(255,255,255,0.08), 0 24px 60px -12px rgba(0,0,0,0.65)',
    backdropFilter: 'blur(28px) saturate(160%)',
    WebkitBackdropFilter: 'blur(28px) saturate(160%)',
  }),
  /** solid teal gradient — primary emphasis */
  solid: (r: number = 24): CSSProperties => ({
    borderRadius: r,
    background: 'linear-gradient(160deg, #0d4441 0%, #0a3633 55%, #0a5155 100%)',
    border: '1px solid rgba(255,255,255,0.10)',
    boxShadow: 'inset 0 1px 0 rgba(255,255,255,0.12), 0 16px 36px -10px rgba(4,26,25,0.6)',
  }),
  /** ai — mint-tinged glass for AI moments */
  ai: (r: number = 24): CSSProperties => ({
    borderRadius: r,
    background: 'linear-gradient(150deg, rgba(0,186,166,0.28), rgba(8,74,77,0.30) 70%)',
    border: '1px solid rgba(75,226,214,0.24)',
    boxShadow: 'inset 0 1px 0 rgba(255,255,255,0.12), 0 12px 32px -8px rgba(0,0,0,0.42)',
    backdropFilter: 'blur(22px) saturate(150%)',
    WebkitBackdropFilter: 'blur(22px) saturate(150%)',
  }),
  hair: '1px solid rgba(255,255,255,0.12)',
  txt: '#fff',
  soft: 'rgba(255,255,255,0.78)',
  faint: 'rgba(255,255,255,0.55)',
  ghost: 'rgba(255,255,255,0.36)',
  spring: 'cubic-bezier(0.34, 1.56, 0.64, 1)',
};

/** Bottom padding so content scrolls clear of the floating glass nav. */
export const NAV_CLEAR = 118;
