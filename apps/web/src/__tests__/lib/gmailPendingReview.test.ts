/**
 * Fix-1 (Wave C): the onboarding-purpose Gmail connect + the server-driven
 * pending-review API that backs the Home "review ready" banner.
 *
 *  - startGmailConnect(true) must hit /gmail/oauth/start?onboarding=1 (and the
 *    no-arg default must stay on the plain URL — every existing caller relies on it).
 *  - getPendingReview parses the body and NEVER throws — a non-ok read resolves to
 *    the silent default so it can't break Home's render.
 *  - ackPendingReview POSTs { sync_id, action }.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('@/lib/auth', () => ({ getAccessToken: vi.fn(async () => 'tok') }));

import {
  startGmailConnect,
  getPendingReview,
  ackPendingReview,
} from '@/lib/api/gmail';

beforeEach(() => {
  // startGmailConnect does a full-page redirect (window.location.href = url); jsdom's
  // real location can't be navigated, so replace it with a plain writable stub.
  Object.defineProperty(window, 'location', {
    configurable: true,
    writable: true,
    value: { href: '' },
  });
});

describe('startGmailConnect (onboarding purpose)', () => {
  it('requests the ?onboarding=1 start URL and redirects to the returned consent URL', async () => {
    const urls: string[] = [];
    global.fetch = vi.fn(async (url: unknown) => {
      urls.push(String(url));
      return { ok: true, json: async () => ({ url: 'https://accounts.google.com/o/oauth2/x' }) } as unknown as Response;
    }) as unknown as typeof fetch;

    await startGmailConnect(true);

    expect(urls[0]).toContain('/gmail/oauth/start?onboarding=1');
    expect(window.location.href).toBe('https://accounts.google.com/o/oauth2/x');
  });

  it('defaults to the plain start URL (no onboarding flag) for existing callers', async () => {
    const urls: string[] = [];
    global.fetch = vi.fn(async (url: unknown) => {
      urls.push(String(url));
      return { ok: true, json: async () => ({ url: 'https://g' }) } as unknown as Response;
    }) as unknown as typeof fetch;

    await startGmailConnect();

    expect(urls[0]).toContain('/gmail/oauth/start');
    expect(urls[0]).not.toContain('onboarding=1');
  });
});

describe('getPendingReview', () => {
  it('returns the parsed body on an ok response', async () => {
    global.fetch = vi.fn(async () => ({
      ok: true,
      json: async () => ({ pending: true, sync_id: 's1', ready_count: 3 }),
    })) as unknown as typeof fetch;

    await expect(getPendingReview()).resolves.toEqual({
      pending: true,
      sync_id: 's1',
      ready_count: 3,
    });
  });

  it('returns the silent default (never throws) on a non-ok response', async () => {
    global.fetch = vi.fn(async () => ({ ok: false, status: 500, json: async () => ({}) })) as unknown as typeof fetch;

    await expect(getPendingReview()).resolves.toEqual({
      pending: false,
      sync_id: null,
      ready_count: 0,
    });
  });
});

describe('ackPendingReview', () => {
  it('POSTs { sync_id, action } with Bearer auth', async () => {
    const calls: { url: string; init: RequestInit }[] = [];
    global.fetch = vi.fn(async (url: unknown, init: unknown) => {
      calls.push({ url: String(url), init: init as RequestInit });
      return { ok: true, status: 204 } as unknown as Response;
    }) as unknown as typeof fetch;

    await ackPendingReview('s1', 'opened');

    const { url, init } = calls[0];
    expect(url).toContain('/gmail/ingest/pending-review/ack');
    expect(init.method).toBe('POST');
    const headers = init.headers as Record<string, string>;
    expect(headers['Content-Type']).toBe('application/json');
    expect(headers['Authorization']).toBe('Bearer tok');
    expect(JSON.parse(init.body as string)).toEqual({ sync_id: 's1', action: 'opened' });
  });
});
