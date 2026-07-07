'use client';

/**
 * WhyThisRecSheet — a reusable transparency sheet ("Why this suggestion?").
 *
 * Design: §7 · P3 "Why this rec" — reasons ranked by confidence, each with a
 * confidence dot (mint = strong, amber = weak) + evidence line, then a
 * "Less like this" / "Looks right" action pair.
 *
 * HONEST / MOCK: there is NO per-recommendation explanation endpoint today. The
 * ranker returns a single headline (the product `reason`), not a scored list of
 * signals. So the reasons shown here are illustrative — the sheet is clearly
 * subtitled with the product it's about, and callers may pass their own
 * `reasons` (e.g. derive one row from the real headline) so at least the top
 * line is real. The feedback buttons are local-only (no signal endpoint wired
 * for per-rec "less like this" yet); pass `onFeedback` to capture intent.
 *
 * Intended entry points (a "Why?" affordance next to a rationale/reason line):
 *   - /shop/[id]         — the AI rationale block (wired below in this pass)
 *   - shop feed cards    — each card's "why" line (future)
 *   - /outfits/[id]      — an outfit's rationale (future)
 *   - home rec cards     — the daily look explanation (future)
 */

import React from 'react';
import { ThumbsDown } from 'lucide-react';
import { Btn, M, Sheet } from '@/components/ds';

/** Confidence dot — mint when strong (≥0.7), amber when weak. Mirrors kit `Dot`. */
export function ConfDot({ conf }: { conf: number }) {
  const low = conf < 0.7;
  return (
    <span
      className="inline-block shrink-0 rounded-full"
      style={{
        width: 7.5,
        height: 7.5,
        background: low ? '#f0a23b' : 'var(--mint)',
        boxShadow: low ? '0 0 0 3px rgba(240,162,59,0.16)' : '0 0 0 3px rgba(75,226,214,0.14)',
      }}
      aria-hidden
    />
  );
}

export interface WhyReason {
  /** 0–1 confidence — drives the dot colour and the intended ranking order. */
  conf: number;
  /** The reason (what the signal claims). */
  text: string;
  /** The evidence behind it. */
  evidence: string;
}

/** Illustrative reasons used when a caller doesn't supply real ones. */
const MOCK_REASONS: WhyReason[] = [
  { conf: 0.94, text: 'You wear slim tops with nothing relaxed below', evidence: 'a gap in several of your saved looks' },
  { conf: 0.86, text: 'The colour matches most of your palette', evidence: 'neutrals rule your closet' },
  { conf: 0.62, text: 'Similar pieces trend in your taste deck', evidence: 'weaker signal — a few likes' },
];

export interface WhyThisRecSheetProps {
  open: boolean;
  onClose: () => void;
  /** e.g. "Pleated trousers · Arket" — names what the suggestion is. */
  subject?: string;
  /**
   * Reasons ranked by confidence. When omitted, illustrative mock reasons are
   * shown. Callers with a real headline should pass at least one real row.
   */
  reasons?: WhyReason[];
  /** Captures "less like this" / "looks right" intent. Local-only today. */
  onFeedback?: (verdict: 'less' | 'right') => void;
}

export function WhyThisRecSheet({ open, onClose, subject, reasons, onFeedback }: WhyThisRecSheetProps) {
  const rows = (reasons && reasons.length > 0 ? reasons : MOCK_REASONS)
    .slice()
    .sort((a, b) => b.conf - a.conf);

  const handle = (verdict: 'less' | 'right') => {
    onFeedback?.(verdict);
    onClose();
  };

  return (
    <Sheet open={open} onClose={onClose} title="Why this suggestion" sub={subject}>
      {/* Honest note: these signals are illustrative, not a live per-rec breakdown. */}
      <div className="mb-3.5 text-[11.5px] leading-snug text-white/[0.45]">
        Ranked by how sure Tailor is. Live per-suggestion breakdowns aren&rsquo;t wired yet —
        these show how the reasoning will read.
      </div>

      <div className="flex flex-col" style={{ gap: 9 }}>
        {rows.map((r, i) => (
          <div
            key={i}
            className="flex items-start gap-3"
            style={{
              padding: '12px 13px',
              borderRadius: 16,
              background: 'rgba(255,255,255,0.055)',
              border: '1px solid rgba(255,255,255,0.09)',
            }}
          >
            <span style={{ marginTop: 4 }}>
              <ConfDot conf={r.conf} />
            </span>
            <div className="min-w-0">
              <div className="text-[13.5px] leading-snug text-white">{r.text}</div>
              <div className="mt-0.5 text-[11px]" style={{ color: M.ghost }}>
                {r.evidence}
              </div>
            </div>
          </div>
        ))}
      </div>

      <div className="mt-3.5 flex" style={{ gap: 9 }}>
        <Btn variant="glass" size="md" fullWidth icon={<ThumbsDown size={14} />} onClick={() => handle('less')}>
          Less like this
        </Btn>
        <Btn variant="ghost" size="md" fullWidth onClick={() => handle('right')}>
          Looks right
        </Btn>
      </div>
    </Sheet>
  );
}
