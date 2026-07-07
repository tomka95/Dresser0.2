'use client';

import { Thinking } from '@/components/ds';

/**
 * Empty-chat greeting: the Thinking mark, a warm line, and starter prompt chips.
 * Shown when a fresh (or incognito) thread has no real turns yet. Tapping a chip
 * sends it as the first message.
 */
export function EmptyGreeting({
  greeting,
  prompts,
  onPick,
}: {
  greeting: string;
  prompts: string[];
  onPick: (prompt: string) => void;
}) {
  return (
    <div
      className="flex flex-1 flex-col items-center justify-center text-center"
      style={{ padding: '0 28px' }}
    >
      <Thinking size={92} />
      <div
        className="mt-3.5 text-[22px] font-bold text-white"
        style={{ letterSpacing: '-0.5px' }}
      >
        Ready when you are
      </div>
      <div
        className="mt-1.5 text-[14px]"
        style={{ color: 'rgba(255,255,255,0.55)', lineHeight: 1.5, maxWidth: 260 }}
      >
        {greeting}
      </div>
      <div className="mt-5 flex flex-wrap justify-center gap-2">
        {prompts.map((c) => (
          <button
            key={c}
            type="button"
            onClick={() => onPick(c)}
            className="rounded-full text-white"
            style={{
              fontSize: 12.5,
              padding: '8px 14px',
              background: 'var(--tr-10)',
              border: '1px solid var(--tr-20)',
            }}
          >
            {c}
          </button>
        ))}
      </div>
    </div>
  );
}
