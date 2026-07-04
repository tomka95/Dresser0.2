'use client';

/**
 * /chat — AI stylist chat (Wave S2: wired to the real SSE backend).
 * Streams tokens into a live assistant bubble, shows tool-call progress
 * ("checking your closet…"), renders composed outfits from OWNED items via
 * ItemImage, and supports image + closet-item attachments.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import type { ChatAttachment, ChatOutfitPayload } from '@tailor/contracts';
import { useRequireAuth } from '@/lib/auth/useRequireAuth';
import { useClosetStore } from '@/stores/useClosetStore';
import {
  getConversationMessages,
  listConversations,
  sendChatMessage,
} from '@/lib/api/chat';
import { AppShell } from '@/components/layout/AppShell';
import { BottomNavBar } from '@/components/layout/BottomNavBar';
import { ItemImage } from '@/components/ui/ItemImage';
import { Sheet, Spark } from '@/components/ds';

interface ChatMessage {
  from: 'ai' | 'user';
  text: string;
  outfit?: ChatOutfitPayload;
  /** Still streaming in. */
  pending?: boolean;
  /** Terminal error styling (quota/timeouts/etc). */
  isError?: boolean;
  /** Client-only object URL for an attached photo shown in the sent bubble.
   *  Display-only — the image is never persisted, so history reloads drop it. */
  imageUrl?: string;
}

interface PendingImage {
  dataBase64: string;
  mimeType: string;
  previewUrl: string;
}

const QUICK_PROMPTS = ['Outfit for today', 'What goes with this?', 'Pack for a trip'];
const MAX_IMAGE_BYTES = 5 * 1024 * 1024;

function OutfitStrip({ outfit }: { outfit: ChatOutfitPayload }) {
  const items = Object.entries(outfit.slots);
  if (items.length === 0) return null;
  return (
    <div className="mt-2 flex gap-2 overflow-x-auto scrollbar-hide">
      {items.map(([slot, item]) => (
        <div key={slot} className="shrink-0" style={{ width: 72 }}>
          <div
            className="overflow-hidden rounded-[10px]"
            style={{ width: 72, aspectRatio: '3/4', border: '1px solid var(--tr-20)' }}
          >
            <ItemImage src={item.imageUrl ?? undefined} alt={item.name} fit="cover" />
          </div>
          <div
            className="mt-1 truncate text-center text-[10px]"
            style={{ color: 'rgba(255,255,255,0.6)' }}
          >
            {item.name}
          </div>
        </div>
      ))}
    </div>
  );
}

export default function ChatPage() {
  const { session, loading } = useRequireAuth('/sign-in', { requireOnboarded: true });
  const isAuth = !!session;

  const items = useClosetStore((state) => state.items);
  const fetchItems = useClosetStore((state) => state.fetchItems);
  const hasFetchedItems = useClosetStore((state) => state.hasFetchedItems);

  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [draft, setDraft] = useState('');
  const [streaming, setStreaming] = useState(false);
  const [toolLabel, setToolLabel] = useState<string | null>(null);
  const [historyLoaded, setHistoryLoaded] = useState(false);
  const [pendingImage, setPendingImage] = useState<PendingImage | null>(null);
  const [attachedItemIds, setAttachedItemIds] = useState<string[]>([]);
  const [pickerOpen, setPickerOpen] = useState(false);

  const conversationIdRef = useRef<string | undefined>(undefined);
  const scrollRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    if (isAuth && !hasFetchedItems) {
      fetchItems();
    }
  }, [isAuth, hasFetchedItems, fetchItems]);

  // Load the latest conversation's transcript once on entry.
  useEffect(() => {
    if (!isAuth || historyLoaded) return;
    let cancelled = false;
    (async () => {
      try {
        const conversations = await listConversations();
        if (cancelled) return;
        if (conversations.length > 0) {
          const latest = conversations[0];
          conversationIdRef.current = latest.id;
          const history = await getConversationMessages(latest.id);
          if (cancelled) return;
          setMessages(
            history.map((m) => ({
              from: m.role === 'assistant' ? ('ai' as const) : ('user' as const),
              text: m.content,
              outfit: m.outfit ?? undefined,
            }))
          );
        } else {
          setMessages([
            { from: 'ai', text: 'Hey — I know your closet. Ask me what to wear.' },
          ]);
        }
      } catch {
        setMessages([
          { from: 'ai', text: 'Hey — I know your closet. Ask me what to wear.' },
        ]);
      } finally {
        if (!cancelled) setHistoryLoaded(true);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [isAuth, historyLoaded]);

  // Keep the newest message in view.
  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [messages, toolLabel]);

  // Abort an in-flight stream on unmount.
  useEffect(() => () => abortRef.current?.abort(), []);

  const attachImage = useCallback((file: File) => {
    if (file.size > MAX_IMAGE_BYTES) {
      setMessages((prev) => [
        ...prev,
        { from: 'ai', text: 'That photo is over 5MB — try a smaller one.', isError: true },
      ]);
      return;
    }
    const reader = new FileReader();
    reader.onload = () => {
      const result = String(reader.result || '');
      const comma = result.indexOf(',');
      if (comma < 0) return;
      setPendingImage({
        dataBase64: result.slice(comma + 1),
        mimeType: file.type || 'image/jpeg',
        previewUrl: URL.createObjectURL(file),
      });
    };
    reader.readAsDataURL(file);
  }, []);

  const send = useCallback(
    (text: string) => {
      const trimmed = text.trim();
      if (!trimmed || streaming) return;

      const attachments: ChatAttachment[] = [];
      if (pendingImage) {
        attachments.push({
          type: 'image',
          dataBase64: pendingImage.dataBase64,
          mimeType: pendingImage.mimeType,
        });
      }
      for (const itemId of attachedItemIds) {
        attachments.push({ type: 'closet_item', itemId });
      }

      setDraft('');
      setPendingImage(null);
      setAttachedItemIds([]);
      setStreaming(true);
      setToolLabel(null);
      setMessages((prev) => [
        ...prev,
        { from: 'user', text: trimmed, imageUrl: pendingImage?.previewUrl },
        { from: 'ai', text: '', pending: true },
      ]);

      const patchLast = (patch: Partial<ChatMessage> | ((m: ChatMessage) => ChatMessage)) => {
        setMessages((prev) => {
          const next = [...prev];
          const last = next[next.length - 1];
          if (!last || last.from !== 'ai') return prev;
          next[next.length - 1] =
            typeof patch === 'function' ? patch(last) : { ...last, ...patch };
          return next;
        });
      };

      const controller = new AbortController();
      abortRef.current = controller;

      void sendChatMessage(
        {
          message: trimmed,
          conversationId: conversationIdRef.current,
          attachments,
          signal: controller.signal,
        },
        {
          onMeta: (meta) => {
            conversationIdRef.current = meta.conversationId;
          },
          onToken: (delta) => {
            setToolLabel(null);
            patchLast((m) => ({ ...m, text: m.text + delta }));
          },
          onTool: (tool) => {
            setToolLabel(tool.status === 'started' ? tool.label : null);
          },
          onOutfit: (outfit) => {
            patchLast({ outfit });
          },
          onDone: () => {
            setToolLabel(null);
            setStreaming(false);
            patchLast({ pending: false });
          },
          onError: (error) => {
            setToolLabel(null);
            setStreaming(false);
            patchLast((m) => ({
              ...m,
              pending: false,
              isError: true,
              text:
                m.text ||
                error.message ||
                'Something went wrong. Try again.',
            }));
          },
        }
      );
    },
    [streaming, pendingImage, attachedItemIds]
  );

  if (loading || !isAuth) {
    return null;
  }

  const attachedItems = items.filter((i) => attachedItemIds.includes(i.id));

  return (
    <AppShell scroll={false}>
      {/* pb clears the fixed bottom nav so the composer stays reachable. */}
      <div className="absolute inset-0 flex flex-col" style={{ paddingBottom: 84 }}>
        {/* Header */}
        <div
          className="flex items-center gap-3"
          style={{ padding: '52px 24px 14px', borderBottom: '1px solid var(--tr-10)' }}
        >
          <Spark size={38} />
          <div>
            <div className="text-[19px] font-bold text-white">Stylist</div>
            <div className="text-[12px]" style={{ color: 'var(--mint)' }}>
              Knows your closet
            </div>
          </div>
        </div>

        {/* Messages */}
        <div
          ref={scrollRef}
          className="flex flex-1 flex-col gap-3.5 overflow-y-auto scrollbar-hide"
          style={{ padding: '18px 20px' }}
        >
          <div className="text-center text-[12px]" style={{ color: 'rgba(255,255,255,0.45)' }}>
            Today
          </div>
          {messages.map((m, i) => (
            <div
              key={i}
              className="max-w-[82%]"
              style={{ alignSelf: m.from === 'user' ? 'flex-end' : 'flex-start' }}
            >
              {m.imageUrl && (
                <div
                  className="mb-1.5 overflow-hidden rounded-[14px]"
                  style={{
                    maxWidth: 180,
                    marginLeft: m.from === 'user' ? 'auto' : 0,
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
                  borderRadius: 18,
                  fontSize: 14.5,
                  lineHeight: 1.45,
                  background: m.from === 'user' ? 'var(--brand-teal)' : 'var(--tr-10)',
                  border:
                    m.from === 'user'
                      ? 'none'
                      : `1px solid ${m.isError ? 'rgba(255,120,120,0.4)' : 'var(--tr-20)'}`,
                  borderBottomRightRadius: m.from === 'user' ? 4 : 18,
                  borderBottomLeftRadius: m.from === 'user' ? 18 : 4,
                  opacity: m.pending && !m.text ? 0.7 : 1,
                }}
              >
                {m.text || (m.pending ? '…' : '')}
              </div>
              {m.outfit && <OutfitStrip outfit={m.outfit} />}
            </div>
          ))}
          {toolLabel && (
            <div
              className="flex items-center gap-2 text-[12.5px]"
              style={{ color: 'var(--mint)', alignSelf: 'flex-start', paddingLeft: 4 }}
            >
              <span
                className="inline-block h-2 w-2 animate-pulse rounded-full"
                style={{ background: 'var(--mint)' }}
              />
              {toolLabel}
            </div>
          )}
        </div>

        {/* Quick prompts + composer */}
        <div style={{ padding: '12px 16px 14px' }}>
          {(pendingImage || attachedItems.length > 0) && (
            <div className="mb-2 flex items-center gap-2 overflow-x-auto scrollbar-hide">
              {pendingImage && (
                <div
                  className="relative shrink-0 overflow-hidden rounded-[10px]"
                  style={{ width: 44, height: 44, border: '1px solid var(--tr-20)' }}
                >
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img
                    src={pendingImage.previewUrl}
                    alt="Attached"
                    className="h-full w-full object-cover"
                  />
                  <button
                    type="button"
                    aria-label="Remove image"
                    onClick={() => setPendingImage(null)}
                    className="absolute right-0 top-0 flex h-4 w-4 items-center justify-center rounded-bl bg-black/70 text-[10px] text-white"
                  >
                    ×
                  </button>
                </div>
              )}
              {attachedItems.map((item) => (
                <div
                  key={item.id}
                  className="relative shrink-0 overflow-hidden rounded-[10px]"
                  style={{ width: 44, height: 44, border: '1px solid var(--tr-20)' }}
                >
                  <ItemImage src={item.imageUrl ?? undefined} alt={item.name} fit="cover" />
                  <button
                    type="button"
                    aria-label={`Remove ${item.name}`}
                    onClick={() =>
                      setAttachedItemIds((prev) => prev.filter((id) => id !== item.id))
                    }
                    className="absolute right-0 top-0 flex h-4 w-4 items-center justify-center rounded-bl bg-black/70 text-[10px] text-white"
                  >
                    ×
                  </button>
                </div>
              ))}
            </div>
          )}

          <div className="mb-2.5 flex gap-2 overflow-x-auto scrollbar-hide">
            {QUICK_PROMPTS.map((s) => (
              <button
                key={s}
                type="button"
                onClick={() => send(s)}
                disabled={streaming}
                className="whitespace-nowrap rounded-full text-white disabled:opacity-40"
                style={{
                  fontSize: 12.5,
                  padding: '7px 12px',
                  background: 'var(--tr-10)',
                  border: '1px solid var(--tr-20)',
                }}
              >
                {s}
              </button>
            ))}
          </div>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              send(draft);
            }}
            className="flex items-center gap-2.5 rounded-full"
            style={{
              background: 'var(--tr-10)',
              border: '1px solid var(--tr-20)',
              padding: '6px 6px 6px 12px',
            }}
          >
            <input
              ref={fileInputRef}
              type="file"
              accept="image/jpeg,image/png,image/webp,image/heic,image/heif,.heic,.heif"
              className="hidden"
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) attachImage(file);
                e.target.value = '';
              }}
            />
            <button
              type="button"
              aria-label="Attach a photo"
              onClick={() => fileInputRef.current?.click()}
              className="flex shrink-0 items-center justify-center rounded-full text-white/70"
              style={{ width: 32, height: 32 }}
            >
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <rect x="3" y="3" width="18" height="18" rx="2" ry="2" />
                <circle cx="8.5" cy="8.5" r="1.5" />
                <path d="M21 15l-5-5L5 21" />
              </svg>
            </button>
            <button
              type="button"
              aria-label="Attach from closet"
              onClick={() => setPickerOpen(true)}
              className="flex shrink-0 items-center justify-center rounded-full text-white/70"
              style={{ width: 32, height: 32 }}
            >
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M12 3a2 2 0 0 1 2 2c0 .5-.2 1-.6 1.4L12 8l8.5 6.4c.9.7.4 2.1-.7 2.1H4.2c-1.1 0-1.6-1.4-.7-2.1L12 8" />
              </svg>
            </button>
            <input
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              placeholder={streaming ? 'Stylist is replying…' : 'Ask your stylist…'}
              disabled={streaming}
              className="min-w-0 flex-1 border-none bg-transparent text-white outline-none placeholder:text-white/40"
              style={{ fontSize: 14.5, fontFamily: 'var(--font-sans)' }}
            />
            <button
              type="submit"
              aria-label="Send"
              disabled={streaming}
              className="flex shrink-0 items-center justify-center rounded-full transition-transform active:scale-90 disabled:opacity-50"
              style={{ width: 40, height: 40, background: 'var(--mint)', color: 'var(--brand-teal)' }}
            >
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
                <path d="M22 2L11 13M22 2l-7 20-4-9-9-4 20-7z" />
              </svg>
            </button>
          </form>
        </div>
      </div>

      {/* Closet-item picker */}
      <Sheet
        open={pickerOpen}
        onClose={() => setPickerOpen(false)}
        title="Attach from closet"
        sub="Pick items to ask about"
      >
        <div className="grid max-h-[50vh] grid-cols-3 gap-2 overflow-y-auto p-1">
          {items.length === 0 && (
            <div className="col-span-3 py-6 text-center text-[13px] text-white/50">
              Your closet is empty — add items first.
            </div>
          )}
          {items.map((item) => {
            const selected = attachedItemIds.includes(item.id);
            return (
              <button
                key={item.id}
                type="button"
                onClick={() =>
                  setAttachedItemIds((prev) =>
                    selected ? prev.filter((id) => id !== item.id) : [...prev, item.id].slice(-3)
                  )
                }
                className="overflow-hidden rounded-[12px] text-left"
                style={{
                  border: selected ? '2px solid var(--mint)' : '1px solid var(--tr-20)',
                }}
              >
                <div style={{ aspectRatio: '3/4' }}>
                  <ItemImage src={item.imageUrl ?? undefined} alt={item.name} fit="cover" />
                </div>
                <div className="truncate px-1.5 py-1 text-[11px] text-white/80">{item.name}</div>
              </button>
            );
          })}
        </div>
        <button
          type="button"
          onClick={() => setPickerOpen(false)}
          className="mt-3 w-full rounded-full py-3 text-[14px] font-semibold"
          style={{ background: 'var(--mint)', color: 'var(--brand-teal)' }}
        >
          Done
        </button>
      </Sheet>

      <BottomNavBar activeRoute="/chat" />
    </AppShell>
  );
}
