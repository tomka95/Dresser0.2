/**
 * Minimal SSE wire parser for the /chat stream (net-new plumbing — the app had
 * no streaming consumer before Wave S2).
 *
 * Pure and incremental so it is unit-testable without a network: feed it raw
 * chunks (which may split events anywhere, including mid-UTF8 — the caller's
 * TextDecoder handles bytes; this handles text), get back completed events plus
 * the unconsumed remainder to carry into the next call.
 */

export interface RawSSEEvent {
  event: string;
  data: string;
}

export interface SSEParseResult {
  events: RawSSEEvent[];
  /** Unterminated tail to prepend to the next chunk. */
  rest: string;
}

/**
 * Parse `buffer + chunk` into completed SSE events (terminated by a blank
 * line). Comment lines (`: keepalive`) are dropped. Multi-line `data:` fields
 * are joined with newlines per the SSE spec.
 */
export function parseSSEChunk(buffer: string, chunk: string): SSEParseResult {
  const text = buffer + chunk;
  // Normalize CRLF so proxies can't break framing.
  const normalized = text.replace(/\r\n/g, '\n');
  const blocks = normalized.split('\n\n');
  const rest = blocks.pop() ?? '';

  const events: RawSSEEvent[] = [];
  for (const block of blocks) {
    let event = 'message';
    const dataLines: string[] = [];
    for (const line of block.split('\n')) {
      if (!line || line.startsWith(':')) continue;
      if (line.startsWith('event:')) {
        event = line.slice('event:'.length).trim();
      } else if (line.startsWith('data:')) {
        dataLines.push(line.slice('data:'.length).replace(/^ /, ''));
      }
    }
    if (dataLines.length > 0) {
      events.push({ event, data: dataLines.join('\n') });
    }
  }
  return { events, rest };
}
