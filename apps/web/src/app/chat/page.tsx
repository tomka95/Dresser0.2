'use client';

/**
 * /chat — AI stylist chat (Wave S2: wired to the real SSE backend).
 * Streams tokens into a live assistant bubble, shows tool-call progress
 * ("checking your closet…"), renders composed outfits from OWNED items via
 * ItemImage, and supports image + closet-item attachments.
 */

import { type ReactNode, useCallback, useEffect, useRef, useState } from 'react';
import type {
  ChatAttachment,
  ChatConversationSummary,
  ChatOutfitPayload,
  OutfitReasonChip,
} from '@tailor/contracts';
import { useRequireAuth } from '@/lib/auth/useRequireAuth';
import { useClosetStore } from '@/stores/useClosetStore';
import {
  deleteConversation,
  getConversationMessages,
  listConversations,
  sendChatMessage,
} from '@/lib/api/chat';
import { sendOutfitFeedback } from '@/lib/api/outfitFeedback';
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

const GREETING = 'Hey — I know your closet. Ask me what to wear.';
const INCOGNITO_GREETING =
  "Incognito on — I won't save or remember this chat. Ask away.";

/** Compact relative time for the history switcher. */
function timeAgo(iso: string | null): string {
  if (!iso) return '';
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return '';
  const s = Math.max(0, Math.floor((Date.now() - then) / 1000));
  if (s < 60) return 'just now';
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  const d = Math.floor(h / 24);
  if (d < 7) return `${d}d ago`;
  return `${Math.floor(d / 7)}w ago`;
}

const IncognitoIcon = ({ size = 19 }: { size?: number }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24" />
    <line x1="1" y1="1" x2="23" y2="23" />
  </svg>
);
const HistoryIcon = () => (
  <svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <line x1="8" y1="6" x2="21" y2="6" /><line x1="8" y1="12" x2="21" y2="12" /><line x1="8" y1="18" x2="21" y2="18" />
    <line x1="3.5" y1="6" x2="3.51" y2="6" /><line x1="3.5" y1="12" x2="3.51" y2="12" /><line x1="3.5" y1="18" x2="3.51" y2="18" />
  </svg>
);
const NewChatIcon = () => (
  <svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M12 20h9" /><path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4 12.5-12.5z" />
  </svg>
);
const TrashIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <polyline points="3 6 5 6 21 6" />
    <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
  </svg>
);

function HeaderButton({
  label,
  active,
  onClick,
  children,
}: {
  label: string;
  active?: boolean;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      aria-label={label}
      aria-pressed={active}
      onClick={onClick}
      className="flex shrink-0 items-center justify-center rounded-full transition-transform active:scale-90"
      style={{
        width: 36,
        height: 36,
        color: active ? 'var(--brand-teal)' : 'rgba(255,255,255,0.85)',
        background: active ? 'var(--mint)' : 'var(--tr-10)',
        border: '1px solid var(--tr-20)',
      }}
    >
      {children}
    </button>
  );
}

interface ClosetItemLite {
  id: string;
  name: string;
  imageUrl?: string | null;
}

/** Reject reason chips shown when the user taps "Not for me". */
const REJECT_CHIPS: { chip: OutfitReasonChip; label: string; direction?: string }[] = [
  { chip: 'formality', label: 'Too dressy', direction: 'too_formal' },
  { chip: 'formality', label: 'Too casual', direction: 'too_casual' },
  { chip: 'color', label: 'Colors off' },
  { chip: 'fit', label: 'Fit' },
  { chip: 'weather', label: 'Wrong for weather' },
  { chip: 'not_my_style', label: 'Not my style' },
];

function OutfitStrip({
  outfit,
  onSlotTap,
  activeSlot,
}: {
  outfit: ChatOutfitPayload;
  onSlotTap?: (slot: string) => void;
  activeSlot?: string | null;
}) {
  const items = Object.entries(outfit.slots);
  if (items.length === 0) return null;
  return (
    <div className="mt-2 flex gap-2 overflow-x-auto scrollbar-hide">
      {items.map(([slot, item]) => {
        const tappable = !!onSlotTap;
        const active = activeSlot === slot;
        const inner = (
          <>
            <div
              className="overflow-hidden rounded-[10px]"
              style={{
                width: 72,
                aspectRatio: '3/4',
                border: active ? '2px solid var(--mint)' : '1px solid var(--tr-20)',
              }}
            >
              <ItemImage src={item.imageUrl ?? undefined} alt={item.name} fit="cover" />
            </div>
            <div
              className="mt-1 truncate text-center text-[10px]"
              style={{ color: active ? 'var(--mint)' : 'rgba(255,255,255,0.6)' }}
            >
              {tappable ? 'Swap' : item.name}
            </div>
          </>
        );
        return tappable ? (
          <button
            key={slot}
            type="button"
            onClick={() => onSlotTap?.(slot)}
            className="shrink-0 text-left"
            style={{ width: 72 }}
            aria-label={`Swap ${item.name}`}
          >
            {inner}
          </button>
        ) : (
          <div key={slot} className="shrink-0" style={{ width: 72 }}>
            {inner}
          </div>
        );
      })}
    </div>
  );
}

/** Reject / modify(swap) / worn affordances on a composed outfit (Wave S3). */
function OutfitActions({
  outfit,
  conversationId,
  closetItems,
}: {
  outfit: ChatOutfitPayload;
  conversationId?: string;
  closetItems: ClosetItemLite[];
}) {
  const [phase, setPhase] = useState<'idle' | 'reject' | 'swap'>('idle');
  const [swapSlot, setSwapSlot] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const itemIds = outfit.itemIds;
  if (itemIds.length === 0) return null;

  const react = async (body: Parameters<typeof sendOutfitFeedback>[0], label: string) => {
    if (busy) return;
    setBusy(true);
    const ack = await sendOutfitFeedback({ ...body, itemIds, conversationId });
    setBusy(false);
    setDone(ack ? label : "Couldn't save that — try again.");
  };

  if (done) {
    return (
      <div className="mt-2 text-[12px]" style={{ color: 'var(--mint)', paddingLeft: 2 }}>
        {done}
      </div>
    );
  }

  const pill = {
    fontSize: 12,
    padding: '6px 11px',
    borderRadius: 999,
    background: 'var(--tr-10)',
    border: '1px solid var(--tr-20)',
    color: 'rgba(255,255,255,0.85)',
  } as const;

  if (phase === 'swap') {
    return (
      <div className="mt-2">
        {!swapSlot ? (
          <>
            <div className="mb-1 text-[11.5px]" style={{ color: 'rgba(255,255,255,0.55)' }}>
              Tap the piece to swap out
            </div>
            <OutfitStrip outfit={outfit} onSlotTap={setSwapSlot} activeSlot={swapSlot} />
            <button type="button" style={pill} className="mt-2" onClick={() => setPhase('idle')}>
              Cancel
            </button>
          </>
        ) : (
          <>
            <div className="mb-1 text-[11.5px]" style={{ color: 'rgba(255,255,255,0.55)' }}>
              Pick a replacement for the {swapSlot}
            </div>
            <div className="grid grid-cols-4 gap-2" style={{ maxHeight: 220, overflowY: 'auto' }}>
              {closetItems.map((it) => (
                <button
                  key={it.id}
                  type="button"
                  disabled={busy || it.id === outfit.slots[swapSlot]?.id}
                  onClick={() =>
                    react(
                      {
                        feedback: 'modify',
                        removedItemId: outfit.slots[swapSlot]?.id,
                        replacementItemId: it.id,
                        slot: swapSlot,
                      },
                      'Got it — I noted that swap.'
                    )
                  }
                  className="overflow-hidden rounded-[9px] disabled:opacity-30"
                  style={{ aspectRatio: '3/4', border: '1px solid var(--tr-20)' }}
                >
                  <ItemImage src={it.imageUrl ?? undefined} alt={it.name} fit="cover" />
                </button>
              ))}
            </div>
            <button type="button" style={pill} className="mt-2" onClick={() => setSwapSlot(null)}>
              Back
            </button>
          </>
        )}
      </div>
    );
  }

  if (phase === 'reject') {
    return (
      <div className="mt-2 flex flex-wrap gap-1.5">
        {REJECT_CHIPS.map(({ chip, label, direction }) => (
          <button
            key={label}
            type="button"
            disabled={busy}
            style={pill}
            onClick={() =>
              react(
                {
                  feedback: 'reject',
                  reasonChips: [chip],
                  directions: direction ? { formality: direction } : undefined,
                },
                "Thanks — I'll keep that in mind."
              )
            }
          >
            {label}
          </button>
        ))}
        <button type="button" style={pill} onClick={() => setPhase('idle')}>
          Cancel
        </button>
      </div>
    );
  }

  return (
    <div className="mt-2 flex flex-wrap gap-1.5">
      <button type="button" style={pill} disabled={busy}
        onClick={() => react({ feedback: 'worn' }, 'Nice — noted you wore it.')}>
        Wore it
      </button>
      <button type="button" style={pill} onClick={() => setPhase('swap')}>
        Swap a piece
      </button>
      <button type="button" style={pill} onClick={() => setPhase('reject')}>
        Not for me
      </button>
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
  const [attachingImage, setAttachingImage] = useState(false);
  const [attachedItemIds, setAttachedItemIds] = useState<string[]>([]);
  const [pickerOpen, setPickerOpen] = useState(false);

  // Sessions UX (S3): incognito mode + thread history switcher.
  const [incognito, setIncognito] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [conversations, setConversations] = useState<ChatConversationSummary[]>([]);
  const [activeId, setActiveId] = useState<string | undefined>(undefined);

  const conversationIdRef = useRef<string | undefined>(undefined);
  const scrollRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    if (isAuth && !hasFetchedItems) {
      fetchItems();
    }
  }, [isAuth, hasFetchedItems, fetchItems]);

  const refreshConversations = useCallback(async () => {
    try {
      setConversations(await listConversations());
    } catch {
      /* history is a convenience — ignore load failures */
    }
  }, []);

  const resetStream = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    setStreaming(false);
    setToolLabel(null);
  }, []);

  const clearComposer = useCallback(() => {
    setDraft('');
    setPendingImage(null);
    setAttachedItemIds([]);
  }, []);

  // Start a fresh, empty (persisted) thread.
  const startNewChat = useCallback(() => {
    resetStream();
    conversationIdRef.current = undefined;
    setActiveId(undefined);
    setIncognito(false);
    clearComposer();
    setMessages([{ from: 'ai', text: GREETING }]);
    setHistoryOpen(false);
  }, [resetStream, clearComposer]);

  // Enter incognito: ephemeral thread the server never persists.
  const enterIncognito = useCallback(() => {
    resetStream();
    conversationIdRef.current = undefined;
    setActiveId(undefined);
    setIncognito(true);
    clearComposer();
    setMessages([{ from: 'ai', text: INCOGNITO_GREETING }]);
    setHistoryOpen(false);
  }, [resetStream, clearComposer]);

  const toggleIncognito = useCallback(() => {
    if (incognito) startNewChat();
    else enterIncognito();
  }, [incognito, startNewChat, enterIncognito]);

  const openHistory = useCallback(() => {
    setHistoryOpen(true);
    void refreshConversations();
  }, [refreshConversations]);

  // Load a saved thread's transcript (leaves incognito).
  const loadConversation = useCallback(
    async (id: string) => {
      resetStream();
      setIncognito(false);
      conversationIdRef.current = id;
      setActiveId(id);
      clearComposer();
      setHistoryOpen(false);
      setMessages([{ from: 'ai', text: '', pending: true }]);
      try {
        const history = await getConversationMessages(id);
        setMessages(
          history.length > 0
            ? history.map((m) => ({
                from: m.role === 'assistant' ? ('ai' as const) : ('user' as const),
                text: m.content,
                outfit: m.outfit ?? undefined,
              }))
            : [{ from: 'ai', text: GREETING }]
        );
      } catch {
        setMessages([
          { from: 'ai', text: 'Could not load that chat. Try again.', isError: true },
        ]);
      }
    },
    [resetStream, clearComposer]
  );

  const removeConversation = useCallback(
    async (id: string) => {
      // Optimistic remove; the row and its messages cascade server-side.
      setConversations((prev) => prev.filter((c) => c.id !== id));
      if (conversationIdRef.current === id) startNewChat();
      try {
        await deleteConversation(id);
      } catch {
        // Re-sync so the UI doesn't lie about what still exists.
        void refreshConversations();
      }
    },
    [startNewChat, refreshConversations]
  );

  // Default to a fresh chat on entry; load the conversation list only to
  // populate the history switcher (never auto-open the latest thread).
  useEffect(() => {
    if (!isAuth || historyLoaded) return;
    setMessages([{ from: 'ai', text: GREETING }]);
    setHistoryLoaded(true);
    void refreshConversations();
  }, [isAuth, historyLoaded, refreshConversations]);

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
    reader.onload = async () => {
      const result = String(reader.result || '');
      const comma = result.indexOf(',');
      if (comma < 0) return;
      // ORIGINAL bytes go to the server untouched — the API transcodes HEIC
      // server-side. The client decode below is ONLY for a displayable preview.
      const dataBase64 = result.slice(comma + 1);
      const mimeType = file.type || 'image/jpeg';

      // Browsers can't paint HEIC in <img>, so a raw object-URL renders blank.
      // Decode HEIC/HEIF to a JPEG blob client-side and preview that instead.
      const looksHeic =
        /\.(heic|heif)$/i.test(file.name) || /^image\/hei[cf]/i.test(file.type);
      let previewUrl = '';
      if (looksHeic) {
        setAttachingImage(true);
        try {
          const { heicTo } = await import('heic-to/next');
          const jpeg = await heicTo({ blob: file, type: 'image/jpeg', quality: 0.8 });
          previewUrl = URL.createObjectURL(jpeg);
        } catch {
          // Decode failed — send anyway (server still transcodes); just no thumb.
          previewUrl = '';
        } finally {
          setAttachingImage(false);
        }
      } else {
        previewUrl = URL.createObjectURL(file);
      }
      setPendingImage({ dataBase64, mimeType, previewUrl });
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
          // Incognito never threads a conversation id — each turn is ephemeral.
          conversationId: incognito ? undefined : conversationIdRef.current,
          attachments,
          noPersist: incognito,
          signal: controller.signal,
        },
        {
          onMeta: (meta) => {
            // Ignore the server's (ephemeral) id in incognito — nothing to resume.
            if (incognito) return;
            conversationIdRef.current = meta.conversationId;
            setActiveId(meta.conversationId);
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
            // A persisted turn may have created/renamed a thread — refresh the
            // switcher. Incognito wrote nothing, so there's nothing to show.
            if (!incognito) void refreshConversations();
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
    [streaming, pendingImage, attachedItemIds, incognito, refreshConversations]
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
          style={{ padding: '52px 18px 14px', borderBottom: '1px solid var(--tr-10)' }}
        >
          <Spark size={38} />
          <div className="min-w-0 flex-1">
            <div className="text-[19px] font-bold text-white">Stylist</div>
            <div
              className="text-[12px]"
              style={{ color: incognito ? 'rgba(255,255,255,0.55)' : 'var(--mint)' }}
            >
              {incognito ? "Incognito · won't be saved" : 'Knows your closet'}
            </div>
          </div>
          <div className="flex items-center gap-1.5">
            <HeaderButton label="Incognito mode" active={incognito} onClick={toggleIncognito}>
              <IncognitoIcon />
            </HeaderButton>
            <HeaderButton label="Chat history" onClick={openHistory}>
              <HistoryIcon />
            </HeaderButton>
            <HeaderButton label="New chat" onClick={startNewChat}>
              <NewChatIcon />
            </HeaderButton>
          </div>
        </div>

        {/* Incognito banner — unmistakable that nothing is being saved. */}
        {incognito && (
          <div
            className="flex items-center gap-2"
            style={{
              padding: '9px 20px',
              background: 'rgba(0,0,0,0.28)',
              borderBottom: '1px solid var(--tr-10)',
              color: 'rgba(255,255,255,0.72)',
              fontSize: 12.5,
            }}
          >
            <IncognitoIcon size={15} />
            <span>Incognito — this chat isn&apos;t saved or remembered.</span>
          </div>
        )}

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
              {m.outfit && m.from === 'ai' && !m.pending && !incognito && (
                <OutfitActions
                  outfit={m.outfit}
                  conversationId={conversationIdRef.current}
                  closetItems={items}
                />
              )}
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
          {(pendingImage || attachingImage || attachedItems.length > 0) && (
            <div className="mb-2 flex items-center gap-2 overflow-x-auto scrollbar-hide">
              {attachingImage && !pendingImage && (
                <div
                  className="flex shrink-0 items-center justify-center rounded-[10px]"
                  style={{ width: 44, height: 44, border: '1px solid var(--tr-20)' }}
                >
                  <span
                    className="inline-block h-4 w-4 animate-spin rounded-full"
                    style={{ border: '2px solid var(--tr-20)', borderTopColor: 'var(--mint)' }}
                  />
                </div>
              )}
              {pendingImage && (
                <div
                  className="relative flex shrink-0 items-center justify-center overflow-hidden rounded-[10px]"
                  style={{ width: 44, height: 44, border: '1px solid var(--tr-20)' }}
                >
                  {pendingImage.previewUrl ? (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img
                      src={pendingImage.previewUrl}
                      alt="Attached"
                      className="h-full w-full object-cover"
                    />
                  ) : (
                    // Decode failed — bytes still send; show a neutral photo glyph.
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="rgba(255,255,255,0.5)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <rect x="3" y="3" width="18" height="18" rx="2" ry="2" />
                      <circle cx="8.5" cy="8.5" r="1.5" />
                      <path d="M21 15l-5-5L5 21" />
                    </svg>
                  )}
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

      {/* Chat history switcher */}
      <Sheet
        open={historyOpen}
        onClose={() => setHistoryOpen(false)}
        title="Your chats"
        sub="Tap to open · trash to delete"
      >
        <button
          type="button"
          onClick={startNewChat}
          className="mb-1 flex w-full items-center gap-3 rounded-[12px] px-3 py-3 text-left"
          style={{ background: 'var(--tr-10)', border: '1px solid var(--tr-20)' }}
        >
          <span className="text-white/85">
            <NewChatIcon />
          </span>
          <span className="text-[15px] font-semibold text-white">New chat</span>
        </button>

        <div className="max-h-[48vh] overflow-y-auto">
          {conversations.length === 0 && (
            <div className="py-8 text-center text-[13px] text-white/50">
              No saved chats yet.
            </div>
          )}
          {conversations.map((c, i) => {
            const active = c.id === activeId;
            return (
              <div
                key={c.id}
                className="flex items-center gap-1"
                style={{ borderTop: i === 0 ? 'none' : '1px solid var(--tr-10)' }}
              >
                <button
                  type="button"
                  onClick={() => loadConversation(c.id)}
                  className="flex min-w-0 flex-1 flex-col gap-0.5 py-[13px] pl-1 pr-2 text-left"
                >
                  <div className="flex items-center gap-2">
                    {active && (
                      <span
                        className="inline-block shrink-0 rounded-full"
                        style={{ width: 7, height: 7, background: 'var(--mint)' }}
                        aria-hidden
                      />
                    )}
                    <span
                      className={`truncate text-[15px] ${active ? 'font-semibold' : 'font-medium'} text-white`}
                    >
                      {c.title || 'Untitled chat'}
                    </span>
                  </div>
                  <span className="text-[12px]" style={{ color: 'rgba(255,255,255,0.45)' }}>
                    {timeAgo(c.updatedAt)}
                  </span>
                </button>
                <button
                  type="button"
                  aria-label={`Delete ${c.title || 'chat'}`}
                  onClick={() => removeConversation(c.id)}
                  className="flex shrink-0 items-center justify-center rounded-full text-white/45 transition-colors active:text-white/80"
                  style={{ width: 36, height: 36 }}
                >
                  <TrashIcon />
                </button>
              </div>
            );
          })}
        </div>
      </Sheet>

      <BottomNavBar activeRoute="/chat" />
    </AppShell>
  );
}
