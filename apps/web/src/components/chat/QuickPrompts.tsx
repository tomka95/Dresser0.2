'use client';

/** Starter-prompt chips above the composer. Disabled while a reply streams. */
export function QuickPrompts({
  prompts,
  disabled,
  onPick,
}: {
  prompts: string[];
  disabled?: boolean;
  onPick: (prompt: string) => void;
}) {
  return (
    <div className="mb-2.5 flex gap-2 overflow-x-auto scrollbar-hide">
      {prompts.map((s) => (
        <button
          key={s}
          type="button"
          onClick={() => onPick(s)}
          disabled={disabled}
          className="whitespace-nowrap rounded-full text-white disabled:opacity-40"
          style={{
            fontSize: 12.5,
            padding: '7px 13px',
            background: 'var(--tr-10)',
            border: '1px solid var(--tr-20)',
          }}
        >
          {s}
        </button>
      ))}
    </div>
  );
}
