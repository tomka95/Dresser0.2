import type { ChatIngestEvent, ChatOutfitPayload } from '@tailor/contracts';

/** One rendered turn in the chat transcript (client-side view model). */
export interface ChatMessage {
  from: 'ai' | 'user';
  text: string;
  outfit?: ChatOutfitPayload;
  /** Closet-add handoff: renders a "ready for review" deep-link button. */
  ingest?: ChatIngestEvent;
  /** Still streaming in. */
  pending?: boolean;
  /** Terminal error styling (quota/timeouts/etc). */
  isError?: boolean;
  /** Client-only object URL for an attached photo shown in the sent bubble.
   *  Display-only — the image is never persisted, so history reloads drop it. */
  imageUrl?: string;
}

/** A pending image attachment: raw bytes for the server + a displayable preview. */
export interface PendingImage {
  dataBase64: string;
  mimeType: string;
  previewUrl: string;
}

/** Minimal closet item shape the chat components need. */
export interface ClosetItemLite {
  id: string;
  name: string;
  imageUrl?: string | null;
}

/** Compact relative time for the history switcher. */
export function timeAgo(iso: string | null): string {
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
