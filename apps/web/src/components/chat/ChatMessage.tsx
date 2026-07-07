'use client';

import { AlertCircle, Hourglass } from 'lucide-react';

import { Spark, TypingDots } from '@/components/ds';

import { OutfitActions } from './OutfitActions';
import { OutfitCard } from './OutfitCard';
import type { ChatMessage as ChatMessageModel, ClosetItemLite } from './types';

/**
 * One chat turn: an optional sent-image thumb, the AI/user/error bubble, then
 * (for AI turns) the composed-outfit card + feedback actions and the in-chat
 * ingest handoff button. Restyled to the §0 glass system: teal user bubble,
 * frost AI bubble with tucked corner, danger tint + "Didn't send" on errors.
 */
export function ChatMessage({
  message,
  conversationId,
  closetItems,
  incognito,
}: {
  message: ChatMessageModel;
  conversationId?: string;
  closetItems: ClosetItemLite[];
  incognito: boolean;
}) {
  const m = message;
  const isUser = m.from === 'user';

  return (
    <div
      className="max-w-[82%]"
      style={{ alignSelf: isUser ? 'flex-end' : 'flex-start' }}
    >
      {m.imageUrl && (
        <div
          className="mb-1.5 overflow-hidden rounded-[14px]"
          style={{
            maxWidth: 180,
            marginLeft: isUser ? 'auto' : 0,
            border: '1px solid var(--tr-20)',
          }}
        >
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={m.imageUrl}
            alt="Attached photo"
            className="block h-auto w-full object-cover"
          />
        </div>
      )}
      <div
        className="whitespace-pre-wrap text-white"
        style={{
          padding: '12px 15px',
          fontSize: 14,
          lineHeight: 1.5,
          borderRadius: isUser ? '20px 20px 6px 20px' : '20px 20px 20px 6px',
          background: isUser
            ? m.isError
              ? 'rgba(251,44,54,0.16)'
              : 'linear-gradient(165deg, #10635c, #0a3633)'
            : 'rgba(255,255,255,0.075)',
          border: isUser
            ? m.isError
              ? '1px solid rgba(251,44,54,0.4)'
              : '1px solid rgba(255,255,255,0.14)'
            : `1px solid ${m.isError ? 'rgba(255,120,120,0.4)' : 'rgba(255,255,255,0.11)'}`,
          boxShadow: isUser && !m.isError ? 'inset 0 1px 0 rgba(255,255,255,0.1)' : undefined,
          backdropFilter: isUser ? undefined : 'blur(14px)',
          WebkitBackdropFilter: isUser ? undefined : 'blur(14px)',
        }}
      >
        {m.text ? (
          m.text
        ) : m.pending ? (
          <span className="inline-flex items-center py-0.5">
            <TypingDots size={5.5} />
          </span>
        ) : (
          ''
        )}
      </div>

      {/* Failed send stays editable upstream; here we mark it clearly. */}
      {isUser && m.isError && (
        <div
          className="mt-1.5 flex items-center justify-end gap-1.5 text-[11.5px]"
          style={{ color: '#ff9096' }}
        >
          <AlertCircle size={12} /> Didn&rsquo;t send
        </div>
      )}

      {/* Offline-queued send — honest: it hasn't sent, and says when it will. */}
      {isUser && m.queued && (
        <div
          className="mt-1.5 flex items-center justify-end gap-1.5 text-[11.5px]"
          style={{ color: '#f0b566' }}
        >
          <Hourglass size={12} /> Queued &mdash; sends when you&rsquo;re back
        </div>
      )}

      {m.outfit && <OutfitCard outfit={m.outfit} />}
      {m.outfit && !isUser && !m.pending && !incognito && (
        <OutfitActions
          outfit={m.outfit}
          conversationId={conversationId}
          closetItems={closetItems}
        />
      )}

      {m.ingest && (
        /* Chat photo → closet handoff: deep-link to the shared review deck scoped
           to this sync (per-item confirm happens there). */
        <a
          href={m.ingest.reviewUrl}
          className="mt-2 inline-flex items-center gap-1.5 rounded-full px-3.5 py-2 text-[13px] font-semibold no-underline"
          style={{
            alignSelf: 'flex-start',
            background: 'linear-gradient(165deg, #52e8dc, #2cc9bc)',
            color: '#06302d',
          }}
        >
          <Spark size={14} style={{ color: '#06302d' }} />
          Review {m.ingest.itemCount} {m.ingest.itemCount === 1 ? 'item' : 'items'} →
        </a>
      )}
    </div>
  );
}
