'use client';

/**
 * /chat — AI stylist chat (Wave S2: wired to the real SSE backend).
 *
 * This page is the ORCHESTRATOR: it owns all logic (auth gate, SSE streaming,
 * incognito sessions, history switcher, attachments + HEIC transcode, outfit
 * feedback) and composes the presentational pieces in components/chat/. The
 * §5 redesign restyles the chrome to the §0 system; the wiring is unchanged.
 *
 * Streams tokens into a live assistant bubble, shows tool-call progress via the
 * Thinking mark, renders composed outfits (collage + per-item strip) with the
 * reject/swap/worn feedback loop, surfaces the in-chat closet-ingest handoff,
 * and supports image + closet-item attachments.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { WifiOff } from 'lucide-react';
import type { ChatAttachment, ChatConversationSummary } from '@tailor/contracts';

import { useRequireAuth } from '@/lib/auth/useRequireAuth';
import { useOnline } from '@/lib/useOnline';
import { useClosetStore } from '@/stores/useClosetStore';
import {
  deleteConversation,
  getConversationMessages,
  listConversations,
  sendChatMessage,
} from '@/lib/api/chat';
import { AppShell } from '@/components/layout/AppShell';
import { BottomNavBar } from '@/components/layout/BottomNavBar';
import { RateLimitState } from '@/components/ds';
import {
  ChatHeader,
  Composer,
  EmptyGreeting,
  HistorySheet,
  IncognitoBanner,
  MessageList,
  QuickPrompts,
  type ChatMessageModel,
  type PendingImage,
} from '@/components/chat';

const QUICK_PROMPTS = ['Outfit for today', 'What goes with this?', 'Pack for a trip'];
const GREETING_PROMPTS = ['Style my black jeans', 'Outfit for a gallery date', "What am I not wearing?"];
const MAX_IMAGE_BYTES = 5 * 1024 * 1024;

const GREETING = 'Hey I am Tailor, how can I help?';
const INCOGNITO_GREETING = "Incognito on — I won't save or remember this chat. Ask away.";

/** Free-tier daily message cap — UI COPY ONLY (no server enforcement). */
const FREE_DAILY_MESSAGES = 20;

export default function ChatPage() {
  const { session, loading } = useRequireAuth('/sign-in', { requireOnboarded: true });
  const isAuth = !!session;
  const online = useOnline();

  const items = useClosetStore((state) => state.items);
  const fetchItems = useClosetStore((state) => state.fetchItems);
  const hasFetchedItems = useClosetStore((state) => state.hasFetchedItems);

  const [messages, setMessages] = useState<ChatMessageModel[]>([]);
  const [draft, setDraft] = useState('');
  const [streaming, setStreaming] = useState(false);
  const [toolLabel, setToolLabel] = useState<string | null>(null);
  const [historyLoaded, setHistoryLoaded] = useState(false);
  const [pendingImage, setPendingImage] = useState<PendingImage | null>(null);
  const [attachingImage, setAttachingImage] = useState(false);
  const [attachedItemIds, setAttachedItemIds] = useState<string[]>([]);

  // Rate-limited (server 429) → show the quota screen instead of the transcript.
  const [rateLimited, setRateLimited] = useState(false);

  // Offline send-queue: text composed while offline is held here (shown as a
  // "Queued — sends when you're back" bubble) and flushed in order on reconnect.
  // Attachments aren't queued (their object URLs / bytes are ephemeral); the
  // composer only queues text while offline.
  const [queuedSends, setQueuedSends] = useState<string[]>([]);

  // Sessions UX (S3): incognito mode + thread history switcher.
  const [incognito, setIncognito] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [conversations, setConversations] = useState<ChatConversationSummary[]>([]);
  const [activeId, setActiveId] = useState<string | undefined>(undefined);
  // History-list load status — surfaced in the sheet (skeleton / retry), no
  // longer swallowed. Tracks the switcher's own fetch, not the transcript.
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyError, setHistoryError] = useState(false);

  const conversationIdRef = useRef<string | undefined>(undefined);
  const scrollRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    if (isAuth && !hasFetchedItems) {
      fetchItems();
    }
  }, [isAuth, hasFetchedItems, fetchItems]);

  const refreshConversations = useCallback(async () => {
    setHistoryLoading(true);
    setHistoryError(false);
    try {
      setConversations(await listConversations());
    } catch {
      // Surface it in the sheet (retry affordance) instead of swallowing.
      setHistoryError(true);
    } finally {
      setHistoryLoading(false);
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
        setMessages([{ from: 'ai', text: 'Could not load that chat. Try again.', isError: true }]);
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
      const looksHeic = /\.(heic|heif)$/i.test(file.name) || /^image\/hei[cf]/i.test(file.type);
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
    (text: string, opts?: { fromQueue?: boolean }) => {
      const trimmed = text.trim();
      if (!trimmed) return;

      // Offline: don't fail the send — hold it in the queue and show an honest
      // "Queued" bubble. It flushes in order once connectivity returns. (Only
      // user-typed sends land here; queued flushes bypass this and go straight
      // out.) Attachments aren't queued.
      if (!online && !opts?.fromQueue) {
        setDraft('');
        setPendingImage(null);
        setAttachedItemIds([]);
        setQueuedSends((prev) => [...prev, trimmed]);
        setMessages((prev) => [...prev, { from: 'user', text: trimmed, queued: true }]);
        return;
      }

      if (streaming) return;

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

      const patchLast = (patch: Partial<ChatMessageModel> | ((m: ChatMessageModel) => ChatMessageModel)) => {
        setMessages((prev) => {
          const next = [...prev];
          const last = next[next.length - 1];
          if (!last || last.from !== 'ai') return prev;
          next[next.length - 1] = typeof patch === 'function' ? patch(last) : { ...last, ...patch };
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
          onIngest: (ingest) => {
            patchLast({ ingest });
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
            // Daily-cap: flip to the quota screen (UI copy only).
            if (error.code === 'rate_limited') setRateLimited(true);
            patchLast((m) => ({
              ...m,
              pending: false,
              isError: true,
              text: m.text || error.message || 'Something went wrong. Try again.',
            }));
          },
        }
      );
    },
    [online, streaming, pendingImage, attachedItemIds, incognito, refreshConversations]
  );

  // Flush the offline queue on reconnect: strip the "queued" pending bubbles and
  // re-send each held message in order (one at a time — send() no-ops while a
  // stream is in flight, and this effect re-runs as streaming settles).
  useEffect(() => {
    if (!online || streaming || queuedSends.length === 0) return;
    const [next, ...rest] = queuedSends;
    setQueuedSends(rest);
    // Drop the placeholder "Queued" bubble for this message; send() re-appends
    // the real user bubble + streaming AI bubble.
    setMessages((prev) => {
      const idx = prev.findIndex((m) => m.queued && m.text === next);
      return idx < 0 ? prev : [...prev.slice(0, idx), ...prev.slice(idx + 1)];
    });
    send(next, { fromQueue: true });
  }, [online, streaming, queuedSends, send]);

  if (loading || !isAuth) {
    return null;
  }

  const attachedItems = items.filter((i) => attachedItemIds.includes(i.id));
  // "Empty" greeting: a fresh/incognito thread with no real turns yet.
  // "Empty" greeting: exactly the single seeded greeting bubble — not a loading
  // placeholder (pending), a load error, or any real turn.
  const isEmpty =
    messages.length === 1 &&
    messages[0].from === 'ai' &&
    !messages[0].outfit &&
    !messages[0].pending &&
    !messages[0].isError &&
    !!messages[0].text;
  const greetingCopy = incognito ? INCOGNITO_GREETING : GREETING;

  const toggleItem = (id: string) =>
    setAttachedItemIds((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id].slice(-3)
    );

  return (
    <AppShell scroll={false}>
      {/* Violet wash while incognito, for an unmistakable mode shift. */}
      {incognito && (
        <div
          className="pointer-events-none absolute inset-0"
          style={{ background: 'linear-gradient(180deg, rgba(52,38,92,0.18), transparent 30%)', zIndex: 5 }}
          aria-hidden
        />
      )}

      {/* pb clears the fixed bottom nav so the composer stays reachable. */}
      <div className="absolute inset-0 flex flex-col" style={{ paddingBottom: 84, zIndex: 10 }}>
        <ChatHeader
          incognito={incognito}
          closetCount={items.length}
          onToggleIncognito={toggleIncognito}
          onOpenHistory={openHistory}
          onNewChat={startNewChat}
        />

        {incognito && <IncognitoBanner />}

        {/* Offline banner — the composer stays typeable; sends queue and flush
            on reconnect (see queuedSends). */}
        {!online && (
          <div style={{ padding: '10px 16px 0' }}>
            <div
              className="mx-auto flex w-fit items-center gap-2 rounded-full text-[12px] font-semibold"
              style={{
                padding: '8px 14px',
                background: 'rgba(240,162,59,0.14)',
                border: '1px solid rgba(240,162,59,0.35)',
                color: '#f0b566',
              }}
              role="status"
            >
              <WifiOff size={14} /> You&rsquo;re offline — messages will send when you&rsquo;re back
            </div>
          </div>
        )}

        {rateLimited ? (
          <div className="flex flex-1 items-center justify-center" style={{ padding: '0 16px' }}>
            <RateLimitState
              compact
              title="Styling limit for today"
              sub={`Free plans include ${FREE_DAILY_MESSAGES} stylist messages a day. It refreshes tomorrow`}
              onBrowseCloset={() => {
                window.location.href = '/closet';
              }}
            />
          </div>
        ) : isEmpty ? (
          <EmptyGreeting greeting={greetingCopy} prompts={GREETING_PROMPTS} onPick={send} />
        ) : (
          <MessageList
            ref={scrollRef}
            messages={messages}
            toolLabel={toolLabel}
            conversationId={conversationIdRef.current}
            closetItems={items}
            incognito={incognito}
          />
        )}

        {!rateLimited && (
          <div>
            {!isEmpty && (
              <div style={{ padding: '0 16px' }}>
                <QuickPrompts prompts={QUICK_PROMPTS} disabled={streaming || !online} onPick={send} />
              </div>
            )}
            <Composer
              draft={draft}
              onDraftChange={setDraft}
              onSend={() => send(draft)}
              streaming={streaming}
              offline={!online}
              incognito={incognito}
              pendingImage={pendingImage}
              attachingImage={attachingImage}
              attachedItems={attachedItems}
              onAttachFile={attachImage}
              onRemoveImage={() => setPendingImage(null)}
              onRemoveItem={(id) => setAttachedItemIds((prev) => prev.filter((x) => x !== id))}
              closetItems={items}
              attachedItemIds={attachedItemIds}
              onToggleItem={toggleItem}
            />
          </div>
        )}
      </div>

      <HistorySheet
        open={historyOpen}
        onClose={() => setHistoryOpen(false)}
        conversations={conversations}
        activeId={activeId}
        loading={historyLoading}
        error={historyError}
        onRetry={refreshConversations}
        onNewChat={startNewChat}
        onOpenConversation={loadConversation}
        onDeleteConversation={removeConversation}
      />

      <BottomNavBar activeRoute="/chat" />
    </AppShell>
  );
}
