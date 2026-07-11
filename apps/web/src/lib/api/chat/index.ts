/**
 * Stylist chat API client (Wave S2).
 *
 * sendChatMessage POSTs to the FastAPI /chat SSE endpoint and forwards typed
 * events to the caller's handlers as they stream in. History reads back the
 * persisted transcript for reloads.
 */
import type {
  ChatAttachment,
  ChatConversationSummary,
  ChatDoneEvent,
  ChatErrorEvent,
  ChatHistoryMessage,
  ChatIngestEvent,
  ChatMetaEvent,
  ChatOutfitPayload,
  ChatToolEvent,
} from '@tailor/contracts';

import { getAccessToken } from '@/lib/auth';
import { API_BASE_URL } from '@/lib/api/base';

import { parseSSEChunk } from './sse';

export interface ChatStreamHandlers {
  onMeta?: (meta: ChatMetaEvent) => void;
  onToken?: (text: string) => void;
  onTool?: (tool: ChatToolEvent) => void;
  onOutfit?: (outfit: ChatOutfitPayload) => void;
  onIngest?: (ingest: ChatIngestEvent) => void;
  onDone?: (done: ChatDoneEvent) => void;
  onError?: (error: ChatErrorEvent) => void;
}

export interface SendChatMessageParams {
  message: string;
  conversationId?: string;
  attachments?: ChatAttachment[];
  /** Incognito: server persists nothing for this turn (no DB trace). */
  noPersist?: boolean;
  /** Abort the stream (e.g. on unmount). */
  signal?: AbortSignal;
}

function friendlyError(status: number, detail: unknown): ChatErrorEvent {
  if (
    detail &&
    typeof detail === 'object' &&
    'code' in (detail as Record<string, unknown>)
  ) {
    const d = detail as { code: string; message?: string };
    return { code: d.code, message: d.message || 'The stylist is unavailable.' };
  }
  if (status === 401 || status === 403) {
    return { code: 'unauthorized', message: 'Please sign in again.' };
  }
  if (status === 413) {
    return { code: 'too_large', message: 'That attachment is too large.' };
  }
  if (status === 429) {
    return { code: 'rate_limited', message: 'Too many messages — give it a moment.' };
  }
  return { code: 'server_error', message: 'Something went wrong. Try again.' };
}

/**
 * Stream one chat turn. Resolves when the stream closes (after done/error).
 * Network/HTTP failures surface through onError — this never throws for
 * expected failure modes.
 */
export async function sendChatMessage(
  params: SendChatMessageParams,
  handlers: ChatStreamHandlers
): Promise<void> {
  const token = await getAccessToken();
  if (!token) {
    handlers.onError?.({ code: 'unauthorized', message: 'Please sign in first.' });
    return;
  }

  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}/chat`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${token}`,
        Accept: 'text/event-stream',
      },
      body: JSON.stringify({
        message: params.message,
        conversationId: params.conversationId,
        attachments: params.attachments ?? [],
        noPersist: params.noPersist ?? false,
      }),
      signal: params.signal,
    });
  } catch (error) {
    if ((error as Error)?.name === 'AbortError') return;
    handlers.onError?.({ code: 'network', message: 'No connection. Check your network.' });
    return;
  }

  if (!response.ok) {
    let detail: unknown = null;
    try {
      detail = (await response.json())?.detail;
    } catch {
      /* non-JSON error body */
    }
    handlers.onError?.(friendlyError(response.status, detail));
    return;
  }

  const reader = response.body?.getReader();
  if (!reader) {
    handlers.onError?.({ code: 'stream', message: 'Streaming is not supported here.' });
    return;
  }

  const decoder = new TextDecoder();
  let buffer = '';
  let sawTerminal = false;

  const dispatch = (event: string, raw: string) => {
    let data: unknown;
    try {
      data = JSON.parse(raw);
    } catch {
      return; // malformed frame — skip, don't kill the stream
    }
    switch (event) {
      case 'meta':
        handlers.onMeta?.(data as ChatMetaEvent);
        break;
      case 'token':
        handlers.onToken?.((data as { text: string }).text ?? '');
        break;
      case 'tool':
        handlers.onTool?.(data as ChatToolEvent);
        break;
      case 'outfit':
        handlers.onOutfit?.(data as ChatOutfitPayload);
        break;
      case 'ingest':
        handlers.onIngest?.(data as ChatIngestEvent);
        break;
      case 'done':
        sawTerminal = true;
        handlers.onDone?.(data as ChatDoneEvent);
        break;
      case 'error':
        sawTerminal = true;
        handlers.onError?.(data as ChatErrorEvent);
        break;
      default:
        break;
    }
  };

  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      const { events, rest } = parseSSEChunk(buffer, decoder.decode(value, { stream: true }));
      buffer = rest;
      for (const e of events) dispatch(e.event, e.data);
    }
  } catch (error) {
    if ((error as Error)?.name !== 'AbortError' && !sawTerminal) {
      handlers.onError?.({ code: 'stream', message: 'The connection dropped mid-reply.' });
    }
    return;
  }

  if (!sawTerminal) {
    handlers.onError?.({ code: 'stream', message: 'The reply ended unexpectedly.' });
  }
}

// --- History ------------------------------------------------------------------
async function authedGet<T>(path: string): Promise<T> {
  const token = await getAccessToken();
  if (!token) throw new Error('Not authenticated. Please sign in first.');
  const response = await fetch(`${API_BASE_URL}${path}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!response.ok) throw new Error('Failed to load chat history');
  return response.json();
}

export async function listConversations(): Promise<ChatConversationSummary[]> {
  const body = await authedGet<{ conversations: ChatConversationSummary[] }>(
    '/chat/conversations'
  );
  return body.conversations;
}

export async function getConversationMessages(
  conversationId: string
): Promise<ChatHistoryMessage[]> {
  const body = await authedGet<{ messages: ChatHistoryMessage[] }>(
    `/chat/conversations/${conversationId}/messages`
  );
  return body.messages;
}

/** Delete one conversation (server cascades its messages). Returns whether a
 *  row was actually removed. */
export async function deleteConversation(conversationId: string): Promise<boolean> {
  const token = await getAccessToken();
  if (!token) throw new Error('Not authenticated. Please sign in first.');
  const response = await fetch(
    `${API_BASE_URL}/chat/conversations/${conversationId}`,
    { method: 'DELETE', headers: { Authorization: `Bearer ${token}` } }
  );
  if (!response.ok) throw new Error('Failed to delete conversation');
  const body = (await response.json()) as { deleted?: boolean };
  return Boolean(body.deleted);
}
