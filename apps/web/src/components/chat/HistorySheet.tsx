'use client';

import { useState } from 'react';
import { PenLine, Trash2 } from 'lucide-react';
import type { ChatConversationSummary } from '@tailor/contracts';

import { Btn, DialogFrame, ErrorState, Icon, Sheet, Sk } from '@/components/ds';

import { timeAgo } from './types';

/** One shimmering placeholder row — matches a real conversation row's layout. */
function SkeletonRow() {
  return (
    <div
      className="flex items-center gap-3"
      style={{ padding: '12.5px 4px' }}
      aria-hidden
    >
      <Sk w={36} h={36} r={12} />
      <div className="flex-1">
        <Sk w="52%" h={12} />
        <Sk w="30%" h={9} style={{ marginTop: 7 }} />
      </div>
    </div>
  );
}

/**
 * Chat history switcher: new-chat · list of saved threads (open on tap) · delete
 * (behind a §0 DialogFrame confirm — the design shows one). Deletion itself is
 * the parent's job; this only gates it on confirmation.
 *
 * Load status is surfaced, not swallowed: a tail skeleton row while the list is
 * loading, and a retry-able error banner if the fetch failed (the parent owns
 * the fetch and passes loading/error/onRetry).
 */
export function HistorySheet({
  open,
  onClose,
  conversations,
  activeId,
  loading = false,
  error = false,
  onRetry,
  onNewChat,
  onOpenConversation,
  onDeleteConversation,
}: {
  open: boolean;
  onClose: () => void;
  conversations: ChatConversationSummary[];
  activeId?: string;
  loading?: boolean;
  error?: boolean;
  onRetry?: () => void;
  onNewChat: () => void;
  onOpenConversation: (id: string) => void;
  onDeleteConversation: (id: string) => void;
}) {
  const [pendingDelete, setPendingDelete] = useState<ChatConversationSummary | null>(null);

  return (
    <>
      <Sheet open={open} onClose={onClose} title="Your chats" sub="Threads keep their outfits and finds.">
        <button
          type="button"
          onClick={onNewChat}
          className="mb-2 flex w-full items-center gap-3 rounded-[14px] px-3.5 py-3 text-left"
          style={{ background: 'var(--tr-10)', border: '1px solid var(--tr-20)' }}
        >
          <span className="text-white/85">
            <PenLine size={17} />
          </span>
          <span className="text-[15px] font-semibold text-white">New chat</span>
        </button>

        <div className="max-h-[48vh] overflow-y-auto">
          {conversations.length === 0 && !loading && !error && (
            <div className="py-8 text-center text-[13px] text-white/50">No saved chats yet.</div>
          )}
          {conversations.map((c) => {
            const active = c.id === activeId;
            return (
              <div
                key={c.id}
                className="flex items-center gap-3"
                style={{ padding: '12.5px 4px', borderBottom: '1px solid rgba(255,255,255,0.07)' }}
              >
                <span
                  className="flex shrink-0 items-center justify-center rounded-[12px]"
                  style={{
                    width: 36,
                    height: 36,
                    background: active ? 'rgba(75,226,214,0.13)' : 'rgba(255,255,255,0.07)',
                    border: active ? '1px solid rgba(75,226,214,0.4)' : '1px solid rgba(255,255,255,0.1)',
                    color: active ? 'var(--mint)' : 'rgba(255,255,255,0.55)',
                  }}
                  aria-hidden
                >
                  <Icon name="CommunicationChatCircle" size={17} />
                </span>
                <button
                  type="button"
                  onClick={() => onOpenConversation(c.id)}
                  className="flex min-w-0 flex-1 flex-col gap-0.5 text-left"
                >
                  <span
                    className={`truncate text-[14.5px] ${active ? 'font-semibold' : 'font-medium'} text-white`}
                  >
                    {c.title || 'Untitled chat'}
                  </span>
                  <span className="text-[11.5px]" style={{ color: 'rgba(255,255,255,0.55)' }}>
                    {timeAgo(c.updatedAt)}
                  </span>
                </button>
                <button
                  type="button"
                  aria-label={`Delete ${c.title || 'chat'}`}
                  onClick={() => setPendingDelete(c)}
                  className="flex shrink-0 items-center justify-center rounded-full text-white/45 transition-colors active:text-white/80"
                  style={{ width: 36, height: 36 }}
                >
                  <Trash2 size={15} />
                </button>
              </div>
            );
          })}

          {/* Tail skeleton while the list loads (shown even alongside cached rows). */}
          {loading && <SkeletonRow />}

          {/* Surfaced load error — not swallowed. Older/newer chats may be missing. */}
          {error && !loading && (
            <div className="mt-2.5">
              <ErrorState
                compact
                title="Couldn’t load your chats"
                sub="They’re safe — the list just didn’t load."
                onRetry={onRetry}
              />
            </div>
          )}
        </div>
      </Sheet>

      <DialogFrame
        open={pendingDelete != null}
        onOpenChange={(o) => {
          if (!o) setPendingDelete(null);
        }}
        iconTone="danger"
        icon={<Trash2 size={24} />}
        title="Delete this chat?"
        sub="This removes the thread and its outfits for good. This can’t be undone."
      >
        <div className="mt-5 flex flex-col gap-2">
          <Btn
            variant="danger"
            fullWidth
            onClick={() => {
              if (pendingDelete) onDeleteConversation(pendingDelete.id);
              setPendingDelete(null);
            }}
          >
            Delete chat
          </Btn>
          <Btn variant="ghost" fullWidth onClick={() => setPendingDelete(null)}>
            Keep it
          </Btn>
        </div>
      </DialogFrame>
    </>
  );
}
