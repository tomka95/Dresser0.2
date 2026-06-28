'use client';

// TODO: stylist chat is mock — no backend conversational endpoint yet.
// sendStylistMessage() returns a canned local reply (see '@/lib/api/chat').

import React, { useEffect, useRef, useState } from 'react';
import { Send } from 'lucide-react';

import { useRequireAuth } from '@/lib/auth/useRequireAuth';
import { useClosetStore } from '@/stores/useClosetStore';
import { sendStylistMessage, type ChatMessage } from '@/lib/api/chat';
import { AppShell } from '@/components/layout/AppShell';
import { BottomNavBar } from '@/components/layout/BottomNavBar';
import { Spark } from '@/components/ui/Spark';

const NAV_HEIGHT = 88;

const QUICK_PROMPTS = ['Outfit for today', 'What goes with this?', 'Pack for a trip'];

let seedId = 0;
const nextId = () => `m-${Date.now()}-${seedId++}`;

const SEED: ChatMessage[] = [
  {
    id: 'seed-1',
    from: 'ai',
    text: 'Morning — it’s 21° and clear today. Want something light?',
  },
];

export default function ChatPage() {
  const { status } = useRequireAuth();
  const isAuth = status === 'authenticated';

  const items = useClosetStore((s) => s.items);
  const fetchItems = useClosetStore((s) => s.fetchItems);
  const hasFetchedItems = useClosetStore((s) => s.hasFetchedItems);

  const [messages, setMessages] = useState<ChatMessage[]>(SEED);
  const [input, setInput] = useState('');
  const [sending, setSending] = useState(false);

  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!isAuth) return;
    if (!hasFetchedItems) fetchItems();
  }, [isAuth, hasFetchedItems, fetchItems]);

  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages, sending]);

  async function send(text: string) {
    const trimmed = text.trim();
    if (!trimmed || sending) return;

    const userMsg: ChatMessage = { id: nextId(), from: 'user', text: trimmed };
    const history = [...messages, userMsg];
    setMessages(history);
    setInput('');
    setSending(true);

    try {
      // TODO: mock — sendStylistMessage has no backend endpoint.
      const reply = await sendStylistMessage(trimmed, history);
      setMessages((prev) => [...prev, reply]);
    } catch {
      setMessages((prev) => [
        ...prev,
        {
          id: nextId(),
          from: 'ai',
          text: 'Sorry — I couldn’t reach the stylist. Try again.',
        },
      ]);
    } finally {
      setSending(false);
    }
  }

  if (status === 'loading' || !isAuth) {
    return (
      <AppShell scroll={false}>
        <div className="absolute inset-0 flex items-center justify-center">
          <div className="h-10 w-40 rounded-xl bg-white/5 animate-pulse" />
        </div>
      </AppShell>
    );
  }

  return (
    <AppShell scroll={false}>
      <div className="absolute inset-0 flex flex-col">
        {/* Header */}
        <div
          className="flex items-center gap-3 px-5 pb-4"
          style={{ paddingTop: 52, borderBottom: '1px solid var(--tr-10)' }}
        >
          <Spark size={38} />
          <div className="min-w-0">
            <div className="text-white" style={{ fontSize: 19, fontWeight: 700 }}>
              Stylist
            </div>
            <div style={{ color: 'var(--mint)', fontSize: 12 }}>Knows your closet</div>
          </div>
        </div>

        {/* Messages */}
        <div
          ref={scrollRef}
          className="flex-1 overflow-y-auto flex flex-col gap-[14px]"
          style={{ padding: '18px 20px' }}
        >
          <div
            className="text-center"
            style={{ color: 'rgba(255,255,255,0.45)', fontSize: 12 }}
          >
            Today
          </div>

          {messages.map((msg) => {
            const isUser = msg.from === 'user';
            const outfitItems =
              msg.outfit
                ?.map((id) => items.find((it) => it.id === id))
                .filter((it): it is NonNullable<typeof it> => Boolean(it)) ?? [];

            return (
              <div
                key={msg.id}
                className="flex flex-col"
                style={{ alignItems: isUser ? 'flex-end' : 'flex-start' }}
              >
                <div
                  style={{
                    maxWidth: '82%',
                    padding: '12px 15px',
                    borderRadius: 18,
                    color: '#fff',
                    fontSize: 14.5,
                    lineHeight: 1.4,
                    ...(isUser
                      ? {
                          borderBottomRightRadius: 4,
                          background: 'var(--brand-teal)',
                        }
                      : {
                          borderBottomLeftRadius: 4,
                          background: 'var(--tr-10)',
                          border: '1px solid var(--tr-20)',
                        }),
                  }}
                >
                  {msg.text}
                </div>

                {/* Outfit thumbnails */}
                {outfitItems.length > 0 && (
                  <div className="flex gap-2 mt-2">
                    {outfitItems.map((it) => (
                      <div
                        key={it.id}
                        className="relative rounded-xl overflow-hidden aspect-[3/4]"
                        style={{ width: 64, background: 'rgba(255,255,255,0.06)' }}
                      >
                        {/* eslint-disable-next-line @next/next/no-img-element */}
                        <img
                          src={it.imageUrl || ''}
                          alt={it.name}
                          loading="lazy"
                          className="w-full h-full object-cover"
                        />
                      </div>
                    ))}
                  </div>
                )}
              </div>
            );
          })}

          {/* Typing indicator */}
          {sending && (
            <div className="flex" style={{ alignItems: 'flex-start' }}>
              <div
                style={{
                  padding: '12px 15px',
                  borderRadius: 18,
                  borderBottomLeftRadius: 4,
                  background: 'var(--tr-10)',
                  border: '1px solid var(--tr-20)',
                  color: 'rgba(255,255,255,0.6)',
                  fontSize: 14.5,
                }}
              >
                ✦ typing…
              </div>
            </div>
          )}
        </div>

        {/* Composer + quick prompts (sits above the nav) */}
        <div style={{ paddingBottom: NAV_HEIGHT }}>
          {/* Quick-prompt chips */}
          <div className="flex gap-2 overflow-x-auto px-5 pb-2.5">
            {QUICK_PROMPTS.map((p) => (
              <button
                key={p}
                type="button"
                onClick={() => send(p)}
                disabled={sending}
                className="whitespace-nowrap rounded-full"
                style={{
                  fontSize: 12.5,
                  color: '#fff',
                  background: 'var(--tr-10)',
                  border: '1px solid var(--tr-20)',
                  padding: '8px 14px',
                }}
              >
                {p}
              </button>
            ))}
          </div>

          {/* Composer pill */}
          <form
            className="px-5 pb-3"
            onSubmit={(e) => {
              e.preventDefault();
              send(input);
            }}
          >
            <div
              className="flex items-center gap-2"
              style={{
                background: 'var(--tr-10)',
                border: '1px solid var(--tr-20)',
                borderRadius: 999,
                padding: '6px 6px 6px 18px',
              }}
            >
              <input
                value={input}
                onChange={(e) => setInput(e.target.value)}
                placeholder="Ask your stylist…"
                className="flex-1 bg-transparent outline-none border-none text-white placeholder:text-white/45"
                style={{ fontSize: 14.5 }}
              />
              <button
                type="submit"
                aria-label="Send"
                disabled={sending || input.trim() === ''}
                className="flex items-center justify-center rounded-full"
                style={{
                  width: 40,
                  height: 40,
                  background: 'var(--mint)',
                  color: '#06403d',
                  flexShrink: 0,
                  opacity: sending || input.trim() === '' ? 0.6 : 1,
                }}
              >
                <Send size={18} />
              </button>
            </div>
          </form>
        </div>
      </div>

      <BottomNavBar active="chat" />
    </AppShell>
  );
}
