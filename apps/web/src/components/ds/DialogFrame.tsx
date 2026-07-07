'use client';

import React from 'react';
import { cn } from '@/lib/utils';

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from '@/components/ui/dialog';
import { M } from './materials';

export type DialogTone = 'mint' | 'danger' | 'amber' | 'plain';

const TONES: Record<DialogTone, { bg: string; bd: string; fg: string }> = {
  mint: { bg: 'rgba(75,226,214,0.13)', bd: 'rgba(75,226,214,0.35)', fg: 'var(--mint)' },
  danger: { bg: 'rgba(251,44,54,0.13)', bd: 'rgba(251,44,54,0.35)', fg: '#ff8087' },
  amber: { bg: 'rgba(240,162,59,0.13)', bd: 'rgba(240,162,59,0.4)', fg: '#f0b566' },
  plain: { bg: 'rgba(255,255,255,0.09)', bd: 'rgba(255,255,255,0.16)', fg: '#fff' },
};

export interface DialogFrameProps {
  open: boolean;
  onOpenChange?: (open: boolean) => void;
  /** Icon medallion glyph (54×54 chip above the title). */
  icon?: React.ReactNode;
  /** Medallion tone — mint (AI/positive), danger, amber (caution), plain. */
  iconTone?: DialogTone;
  title?: string;
  sub?: string;
  /** 330px wide instead of 306px. */
  wide?: boolean;
  children?: React.ReactNode;
}

/**
 * §0 · G8 — Unified centered dialog: composes the Radix dialog (focus trap,
 * escape, a11y) with the deep-glass confirm styling — icon medallion, centered
 * title/sub, then your action stack as children.
 *
 *   <DialogFrame open={open} onOpenChange={setOpen} iconTone="danger"
 *     icon={<Trash2 size={24} />} title="Delete this chat?" sub="…">
 *     <div className="mt-5 flex flex-col gap-2">
 *       <Btn variant="danger" fullWidth>Delete chat</Btn>
 *       <Btn variant="ghost" fullWidth onClick={() => setOpen(false)}>Keep it</Btn>
 *     </div>
 *   </DialogFrame>
 */
export function DialogFrame({
  open,
  onOpenChange,
  icon,
  iconTone = 'mint',
  title,
  sub,
  wide = false,
  children,
}: DialogFrameProps) {
  const t = TONES[iconTone];
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className={cn('block text-center', wide ? 'w-[330px]' : 'w-[306px]')}>
        {icon && (
          <div
            className="mx-auto mb-[15px] flex items-center justify-center"
            style={{
              width: 54,
              height: 54,
              borderRadius: 19,
              background: t.bg,
              border: `1px solid ${t.bd}`,
              color: t.fg,
            }}
            aria-hidden
          >
            {icon}
          </div>
        )}
        {title && (
          <DialogTitle
            className="text-white"
            style={{ fontSize: 18.5, fontWeight: 650, letterSpacing: '-0.35px', lineHeight: 1.25 }}
          >
            {title}
          </DialogTitle>
        )}
        {sub && (
          <DialogDescription
            className="mt-[7px]"
            style={{ color: M.faint, fontSize: 13.5, lineHeight: 1.55 }}
          >
            {sub}
          </DialogDescription>
        )}
        {children}
      </DialogContent>
    </Dialog>
  );
}
