/**
 * Stylist chat contracts (Wave S2).
 *
 * POST /chat streams Server-Sent Events; these types describe the request body,
 * every SSE event payload, and the history read endpoints.
 */

export interface ChatImageAttachment {
  type: 'image';
  /** Base64 of the raw image bytes (server sanitizes + strips EXIF). */
  dataBase64: string;
  mimeType: string;
}

export interface ChatClosetItemAttachment {
  type: 'closet_item';
  itemId: string;
}

export type ChatAttachment = ChatImageAttachment | ChatClosetItemAttachment;

export interface ChatRequest {
  message: string;
  conversationId?: string;
  attachments?: ChatAttachment[];
}

/** One item inside a composed outfit (compact server projection). */
export interface OutfitSlotItem {
  id: string;
  name: string;
  category?: string | null;
  color?: string | null;
  imageUrl?: string | null;
  [key: string]: unknown;
}

export interface ChatOutfitPayload {
  slots: Record<string, OutfitSlotItem>;
  itemIds: string[];
  rationale: string;
  warnings: string[];
}

// --- SSE event payloads -----------------------------------------------------
export interface ChatMetaEvent {
  conversationId: string;
  model: string;
}

export interface ChatTokenEvent {
  text: string;
}

export interface ChatToolEvent {
  name: string;
  status: 'started' | 'finished';
  label: string;
}

export interface ChatDoneEvent {
  conversationId: string;
  messageId: string;
  inputTokens: number;
  outputTokens: number;
  costUsd: number;
  model: string;
}

export interface ChatErrorEvent {
  code:
    | 'rate_limited'
    | 'quota_exceeded'
    | 'concurrent_limit'
    | 'timeout'
    | 'turn_failed'
    | 'server_error'
    | string;
  message: string;
}

export type ChatSSEEvent =
  | { event: 'meta'; data: ChatMetaEvent }
  | { event: 'token'; data: ChatTokenEvent }
  | { event: 'tool'; data: ChatToolEvent }
  | { event: 'outfit'; data: ChatOutfitPayload }
  | { event: 'done'; data: ChatDoneEvent }
  | { event: 'error'; data: ChatErrorEvent };

// --- History reads -----------------------------------------------------------
export interface ChatConversationSummary {
  id: string;
  title: string | null;
  updatedAt: string | null;
}

export interface ChatHistoryMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  outfit: ChatOutfitPayload | null;
  createdAt: string | null;
}
