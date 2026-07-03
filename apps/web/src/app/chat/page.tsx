'use client';

/**
 * /chat — AI stylist chat (FRONTEND-ONLY: no chat backend yet).
 * Seeded conversation in the design's voice; the composer works locally and the
 * "assistant" replies with a holding message until the real endpoint exists.
 * Outfit thumbnails attach REAL closet item images when available.
 */

import { useEffect, useRef, useState } from 'react';
import { useRequireAuth } from '@/lib/auth/useRequireAuth';
import { useClosetStore } from '@/stores/useClosetStore';
import { AppShell } from '@/components/layout/AppShell';
import { BottomNavBar } from '@/components/layout/BottomNavBar';
import { ItemImage } from '@/components/ui/ItemImage';
import { Spark } from '@/components/ds';

interface ChatMessage {
  from: 'ai' | 'user';
  text: string;
  /** Closet item image URLs to show as outfit thumbnails under an AI reply. */
  outfitImages?: string[];
}

const QUICK_PROMPTS = ['Outfit for today', 'What goes with this?', 'Pack for a trip'];

export default function ChatPage() {
  const { session, loading } = useRequireAuth('/sign-in', { requireOnboarded: true });
  const isAuth = !!session;

  const items = useClosetStore((state) => state.items);
  const fetchItems = useClosetStore((state) => state.fetchItems);
  const hasFetchedItems = useClosetStore((state) => state.hasFetchedItems);

  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [draft, setDraft] = useState('');
  const seededRef = useRef(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const replyTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (isAuth && !hasFetchedItems) {
      fetchItems();
    }
  }, [isAuth, hasFetchedItems, fetchItems]);

  // Seed the conversation once (with real closet thumbnails when we have them).
  useEffect(() => {
    if (!isAuth || seededRef.current) return;
    seededRef.current = true;
    const thumbs = items
      .filter((i) => i.imageUrl)
      .slice(0, 3)
      .map((i) => i.imageUrl as string);
    setMessages([
      { from: 'ai', text: 'Morning! It’s 21° and clear today — want something light?' },
      { from: 'user', text: 'What goes with my black jeans for the meeting at 10?' },
      {
        from: 'ai',
        text: 'A light shirt with your boots reads sharp but relaxed. Layer a coat if it cools off.',
        outfitImages: thumbs.length > 0 ? thumbs : undefined,
      },
    ]);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isAuth, items]);

  // Keep the newest message in view.
  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [messages]);

  useEffect(() => () => {
    if (replyTimerRef.current) clearTimeout(replyTimerRef.current);
  }, []);

  const send = (text: string) => {
    const trimmed = text.trim();
    if (!trimmed) return;
    setDraft('');
    setMessages((prev) => [...prev, { from: 'user', text: trimmed }]);
    // Holding reply until the stylist backend lands.
    replyTimerRef.current = setTimeout(() => {
      setMessages((prev) => [
        ...prev,
        {
          from: 'ai',
          text: 'I’m still learning your closet — full styling chat is coming soon. Meanwhile, check Outfits for today’s looks.',
        },
      ]);
    }, 600);
  };

  if (loading || !isAuth) {
    return null;
  }

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
        <div ref={scrollRef} className="flex flex-1 flex-col gap-3.5 overflow-y-auto scrollbar-hide" style={{ padding: '18px 20px' }}>
          <div className="text-center text-[12px]" style={{ color: 'rgba(255,255,255,0.45)' }}>
            Today
          </div>
          {messages.map((m, i) => (
            <div key={i} className="max-w-[82%]" style={{ alignSelf: m.from === 'user' ? 'flex-end' : 'flex-start' }}>
              <div
                className="text-white"
                style={{
                  padding: '12px 15px',
                  borderRadius: 18,
                  fontSize: 14.5,
                  lineHeight: 1.45,
                  background: m.from === 'user' ? 'var(--brand-teal)' : 'var(--tr-10)',
                  border: m.from === 'user' ? 'none' : '1px solid var(--tr-20)',
                  borderBottomRightRadius: m.from === 'user' ? 4 : 18,
                  borderBottomLeftRadius: m.from === 'user' ? 18 : 4,
                }}
              >
                {m.text}
              </div>
              {m.outfitImages && (
                <div className="mt-2 flex gap-2">
                  {m.outfitImages.map((src, j) => (
                    <div
                      key={j}
                      className="overflow-hidden rounded-[10px]"
                      style={{ width: 64, aspectRatio: '3/4', border: '1px solid var(--tr-20)' }}
                    >
                      <ItemImage src={src} alt="Outfit item" fit="cover" />
                    </div>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>

        {/* Quick prompts + composer */}
        <div style={{ padding: '12px 16px 14px' }}>
          <div className="mb-2.5 flex gap-2 overflow-x-auto scrollbar-hide">
            {QUICK_PROMPTS.map((s) => (
              <button
                key={s}
                type="button"
                onClick={() => send(s)}
                className="whitespace-nowrap rounded-full text-white"
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
            style={{ background: 'var(--tr-10)', border: '1px solid var(--tr-20)', padding: '6px 6px 6px 18px' }}
          >
            <input
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              placeholder="Ask your stylist…"
              className="min-w-0 flex-1 border-none bg-transparent text-white outline-none placeholder:text-white/40"
              style={{ fontSize: 14.5, fontFamily: 'var(--font-sans)' }}
            />
            <button
              type="submit"
              aria-label="Send"
              className="flex shrink-0 items-center justify-center rounded-full transition-transform active:scale-90"
              style={{ width: 40, height: 40, background: 'var(--mint)', color: 'var(--brand-teal)' }}
            >
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
                <path d="M22 2L11 13M22 2l-7 20-4-9-9-4 20-7z" />
              </svg>
            </button>
          </form>
        </div>
      </div>

      <BottomNavBar activeRoute="/chat" />
    </AppShell>
  );
}
