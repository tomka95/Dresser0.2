import React from 'react';

/** Multicolor Gmail envelope mark used on ingest options and connect cards. */
export function GmailGlyph({ size = 22 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden>
      <path
        d="M2 6.5A1.5 1.5 0 0 1 3.5 5h17A1.5 1.5 0 0 1 22 6.5v11a1.5 1.5 0 0 1-1.5 1.5h-17A1.5 1.5 0 0 1 2 17.5z"
        fill="#fff"
      />
      <path d="M3 6.5l9 6 9-6" stroke="#ea4335" strokeWidth="1.8" fill="none" />
      <path d="M22 6.7V17.5a1.5 1.5 0 0 1-1.5 1.5H18V9.2l4-2.5z" fill="#34a853" />
      <path d="M2 6.7V17.5A1.5 1.5 0 0 0 3.5 19H6V9.2L2 6.7z" fill="#4285f4" />
    </svg>
  );
}
