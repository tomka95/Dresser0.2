'use client';

import { Glasses, PenLine } from 'lucide-react';

import { M, RoundBtn, StylistMark } from '@/components/ds';

/**
 * Chat chrome: online-dot stylist mark · title + closet-aware sub · incognito
 * toggle · history · new-chat. Restyled to the §0 system (StylistMark medallion,
 * violet incognito accent) from the ~1075-line monolith's inline header.
 */
export function ChatHeader({
  incognito,
  closetCount,
  onToggleIncognito,
  onOpenHistory,
  onNewChat,
}: {
  incognito: boolean;
  closetCount: number;
  onToggleIncognito: () => void;
  onOpenHistory: () => void;
  onNewChat: () => void;
}) {
  return (
    <div
      className="flex items-center gap-3"
      style={{ padding: '52px 18px 12px', borderBottom: '1px solid var(--tr-10)' }}
    >
      <div className="relative shrink-0">
        <div
          className="flex items-center justify-center rounded-full"
          style={{
            width: 42,
            height: 42,
            background: 'rgba(75,226,214,0.13)',
            border: '1px solid rgba(75,226,214,0.4)',
            color: 'var(--mint)',
          }}
        >
          <StylistMark size={22} />
        </div>
        <span
          className="absolute rounded-full"
          style={{
            bottom: 1,
            right: 1,
            width: 10,
            height: 10,
            background: '#0acf83',
            border: '2px solid #0d1716',
          }}
          aria-hidden
        />
      </div>
      <div className="min-w-0 flex-1">
        <div className="text-[17px] font-semibold text-white" style={{ letterSpacing: '-0.3px' }}>
          Stylist
        </div>
        <div
          className="text-[11.5px]"
          style={{ color: incognito ? '#b3a0ef' : M.faint, marginTop: 1 }}
        >
          {incognito
            ? 'Incognito — not learning'
            : `Knows your closet${closetCount > 0 ? ` · ${closetCount} pieces` : ''}`}
        </div>
      </div>
      <RoundBtn
        size={38}
        aria-label="Incognito mode"
        aria-pressed={incognito}
        on={incognito}
        onClick={onToggleIncognito}
        icon={<Glasses size={17} />}
        style={
          incognito
            ? {
                background: 'rgba(150,120,230,0.16)',
                border: '1px solid rgba(150,120,230,0.45)',
                color: '#b3a0ef',
              }
            : undefined
        }
      />
      <RoundBtn
        size={38}
        aria-label="Chat history"
        onClick={onOpenHistory}
        icon={
          <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <line x1="8" y1="6" x2="21" y2="6" /><line x1="8" y1="12" x2="21" y2="12" /><line x1="8" y1="18" x2="21" y2="18" />
            <line x1="3.5" y1="6" x2="3.51" y2="6" /><line x1="3.5" y1="12" x2="3.51" y2="12" /><line x1="3.5" y1="18" x2="3.51" y2="18" />
          </svg>
        }
      />
      <RoundBtn
        size={38}
        aria-label="New chat"
        onClick={onNewChat}
        icon={<PenLine size={17} />}
      />
    </div>
  );
}
