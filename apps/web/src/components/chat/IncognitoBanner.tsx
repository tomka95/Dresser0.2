'use client';

import { Glasses } from 'lucide-react';

/**
 * Violet "not learning" pill under the header while incognito is on — makes it
 * unmistakable that this chat won't shape the style profile (zero-trace).
 */
export function IncognitoBanner() {
  return (
    <div style={{ padding: '10px 16px 0' }}>
      <div
        className="mx-auto flex w-fit items-center gap-2 rounded-full text-[12px] font-semibold"
        style={{
          padding: '8px 14px',
          background: 'rgba(150,120,230,0.13)',
          border: '1px solid rgba(150,120,230,0.4)',
          color: '#b3a0ef',
        }}
        role="status"
      >
        <Glasses size={14} /> Incognito — this chat won&rsquo;t shape your style profile
      </div>
    </div>
  );
}
