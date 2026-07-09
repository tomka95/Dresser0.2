/**
 * Phase B (Fix 4): regenerateItemImage now posts multipart/form-data (optional reason +
 * optional reference image) and must NOT set Content-Type (the browser adds the boundary).
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('@/lib/auth', () => ({ getAccessToken: vi.fn(async () => 'tok') }));

import { regenerateItemImage } from '@/lib/api/closet';

describe('regenerateItemImage (multipart)', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('sends FormData with reason + reference and no Content-Type header', async () => {
    const calls: any[] = [];
    global.fetch = vi.fn(async (url: any, init: any) => {
      calls.push({ url, init });
      return { ok: true, json: async () => ({ status: 'regenerating', generationStatus: 'generating' }) } as any;
    }) as any;

    const file = new File([new Uint8Array([1, 2, 3])], 'ref.png', { type: 'image/png' });
    const res = await regenerateItemImage('item-1', 'red swoosh', file);

    expect(res.generationStatus).toBe('generating');
    const { url, init } = calls[0];
    expect(String(url)).toContain('/closet/item-1/regenerate');
    expect(init.method).toBe('POST');
    expect(init.headers['Content-Type']).toBeUndefined(); // browser sets the boundary
    expect(init.headers['Authorization']).toBe('Bearer tok');
    expect(init.body).toBeInstanceOf(FormData);
    const fd = init.body as FormData;
    expect(fd.get('reason')).toBe('red swoosh');
    expect(fd.get('reference')).toBeInstanceOf(File);
  });

  it('omits reason + reference when not provided', async () => {
    const calls: any[] = [];
    global.fetch = vi.fn(async (_url: any, init: any) => {
      calls.push({ init });
      return { ok: true, json: async () => ({}) } as any;
    }) as any;

    await regenerateItemImage('item-2');
    const fd = calls[0].init.body as FormData;
    expect(fd.get('reason')).toBeNull();
    expect(fd.get('reference')).toBeNull();
  });
});
