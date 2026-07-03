import { describe, expect, it } from 'vitest';

import { parseSSEChunk } from '@/lib/api/chat/sse';

describe('parseSSEChunk', () => {
  it('parses a complete event', () => {
    const { events, rest } = parseSSEChunk('', 'event: token\ndata: {"text":"hi"}\n\n');
    expect(events).toEqual([{ event: 'token', data: '{"text":"hi"}' }]);
    expect(rest).toBe('');
  });

  it('carries a partial event across chunks', () => {
    const first = parseSSEChunk('', 'event: token\ndata: {"te');
    expect(first.events).toEqual([]);
    expect(first.rest).toBe('event: token\ndata: {"te');

    const second = parseSSEChunk(first.rest, 'xt":"hi"}\n\nevent: done\ndata: {}\n\n');
    expect(second.events).toEqual([
      { event: 'token', data: '{"text":"hi"}' },
      { event: 'done', data: '{}' },
    ]);
    expect(second.rest).toBe('');
  });

  it('parses multiple events in one chunk, preserving order', () => {
    const chunk =
      'event: meta\ndata: {"conversationId":"c1"}\n\n' +
      'event: token\ndata: {"text":"a"}\n\n' +
      'event: token\ndata: {"text":"b"}\n\n';
    const { events } = parseSSEChunk('', chunk);
    expect(events.map((e) => e.event)).toEqual(['meta', 'token', 'token']);
  });

  it('drops keepalive comments without breaking framing', () => {
    const { events, rest } = parseSSEChunk(
      '',
      ': keepalive\n\nevent: token\ndata: {"text":"x"}\n\n'
    );
    expect(events).toEqual([{ event: 'token', data: '{"text":"x"}' }]);
    expect(rest).toBe('');
  });

  it('normalizes CRLF line endings', () => {
    const { events } = parseSSEChunk('', 'event: done\r\ndata: {}\r\n\r\n');
    expect(events).toEqual([{ event: 'done', data: '{}' }]);
  });

  it('joins multi-line data fields with newlines', () => {
    const { events } = parseSSEChunk('', 'event: token\ndata: line1\ndata: line2\n\n');
    expect(events).toEqual([{ event: 'token', data: 'line1\nline2' }]);
  });

  it('ignores blocks without data', () => {
    const { events } = parseSSEChunk('', 'event: ghost\n\n');
    expect(events).toEqual([]);
  });
});
