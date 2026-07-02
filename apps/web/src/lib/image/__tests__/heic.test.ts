/**
 * HEIC detection + transcode. The libheif-wasm decoder ('heic-to') is mocked so the
 * tests exercise our wrapper (detection heuristics, JPEG File shaping, failure →
 * typed error) without loading wasm.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';

const heicTo = vi.fn();
vi.mock('heic-to', () => ({ heicTo: (...args: unknown[]) => heicTo(...args) }));

import { looksLikeHeic, transcodeHeicToJpeg, HeicTranscodeError } from '../heic';

const file = (name: string, type = ''): File => new File(['x'], name, { type });

beforeEach(() => {
  vi.clearAllMocks();
});

describe('looksLikeHeic', () => {
  it('matches by MIME type', () => {
    expect(looksLikeHeic(file('a', 'image/heic'))).toBe(true);
    expect(looksLikeHeic(file('a', 'image/heif'))).toBe(true);
    expect(looksLikeHeic(file('a', 'image/heic-sequence'))).toBe(true);
  });

  it('matches by extension when the MIME is empty or odd (common for HEIC)', () => {
    expect(looksLikeHeic(file('IMG_1234.HEIC', ''))).toBe(true);
    expect(looksLikeHeic(file('photo.heif', 'application/octet-stream'))).toBe(true);
  });

  it('is false for standard web image formats', () => {
    expect(looksLikeHeic(file('a.jpg', 'image/jpeg'))).toBe(false);
    expect(looksLikeHeic(file('a.png', 'image/png'))).toBe(false);
    expect(looksLikeHeic(file('a.webp', 'image/webp'))).toBe(false);
  });
});

describe('transcodeHeicToJpeg', () => {
  it('returns a JPEG File (.jpg name) built from the decoded blob, quality 0.9', async () => {
    heicTo.mockResolvedValue(new Blob(['jpeg-bytes'], { type: 'image/jpeg' }));

    const out = await transcodeHeicToJpeg(file('IMG_1234.HEIC', 'image/heic'));

    expect(out).toBeInstanceOf(File);
    expect(out.type).toBe('image/jpeg');
    expect(out.name).toBe('IMG_1234.jpg');
    expect(out.size).toBe('jpeg-bytes'.length);
    expect(heicTo).toHaveBeenCalledWith({
      blob: expect.any(File),
      type: 'image/jpeg',
      quality: 0.9,
    });
  });

  it('names extension-less inputs sensibly', async () => {
    heicTo.mockResolvedValue(new Blob(['j'], { type: 'image/jpeg' }));
    const out = await transcodeHeicToJpeg(file('livephoto', 'image/heic'));
    expect(out.name).toBe('livephoto.jpg');
  });

  it('throws HeicTranscodeError (not the raw decoder error) when decoding fails', async () => {
    heicTo.mockRejectedValue(new Error('libheif wasm exploded'));
    await expect(
      transcodeHeicToJpeg(file('a.heic', 'image/heic')),
    ).rejects.toBeInstanceOf(HeicTranscodeError);
  });

  it('throws HeicTranscodeError on empty output (never returns partial bytes)', async () => {
    heicTo.mockResolvedValue(new Blob([], { type: 'image/jpeg' }));
    await expect(
      transcodeHeicToJpeg(file('a.heic', 'image/heic')),
    ).rejects.toBeInstanceOf(HeicTranscodeError);
  });
});
