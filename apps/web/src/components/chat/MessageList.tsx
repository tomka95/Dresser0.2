'use client';

import { forwardRef } from 'react';

import { Thinking } from '@/components/ds';

import { ChatMessage } from './ChatMessage';
import type { ChatMessage as ChatMessageModel, ClosetItemLite } from './types';

/**
 * Scrolling transcript. Owns the day divider, the message bubbles, and the
 * tool-progress row (the Thinking mark + the server's tool label while a tool
 * runs). The parent forwards a ref for autoscroll and passes the live toolLabel.
 */
export const MessageList = forwardRef<
  HTMLDivElement,
  {
    messages: ChatMessageModel[];
    toolLabel: string | null;
    conversationId?: string;
    closetItems: ClosetItemLite[];
    incognito: boolean;
  }
>(function MessageList({ messages, toolLabel, conversationId, closetItems, incognito }, ref) {
  return (
    <div
      ref={ref}
      className="flex flex-1 flex-col gap-3 overflow-y-auto scrollbar-hide"
      style={{ padding: '14px 16px' }}
    >
      <div className="text-center text-[12px]" style={{ color: 'rgba(255,255,255,0.45)' }}>
        Today
      </div>
      {messages.map((m, i) => (
        <ChatMessage
          key={i}
          message={m}
          conversationId={conversationId}
          closetItems={closetItems}
          incognito={incognito}
        />
      ))}
      {toolLabel && (
        <div
          className="flex items-center gap-2 text-[12px]"
          style={{ color: 'var(--mint)', alignSelf: 'flex-start', paddingLeft: 2 }}
        >
          <Thinking size={22} />
          <span style={{ fontFamily: 'ui-monospace, Menlo, monospace' }}>{toolLabel}</span>
        </div>
      )}
    </div>
  );
});
