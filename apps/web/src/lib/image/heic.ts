/**
 * HEIC/HEIF → JPEG client-side transcode (mobile-web).
 *
 * iPhones shoot HEIC by default, but the ingestion pipeline (and every browser's
 * canvas/`<img>`) speaks JPEG/PNG/WebP. We transcode HEIC to JPEG IN THE BROWSER,
 * ONCE, at file-selection time — the resulting JPEG becomes THE canonical bytes for
 * the whole detect → select → commit flow (local preview, the sha256 the server
 * binds the detect session to, and the commit re-upload). Transcoding once and
 * reusing that single File is what keeps detect and commit byte-identical; never
 * re-transcode a file or the server-side sha rebind will miss.
 *
 * The decoder (heic-to, libheif-wasm) is heavy, so it is loaded via a DYNAMIC import
 * INSIDE {@link transcodeHeicToJpeg} — it only enters the bundle when a HEIC file is
 * actually selected. JPEG/PNG/WebP users never download it. Keep the import dynamic;
 * a top-level import would pull the wasm into the main chunk.
 */

/** Output JPEG quality for the transcode (0..1). */
const JPEG_QUALITY = 0.9;

const HEIC_MIME = new Set([
  'image/heic',
  'image/heif',
  'image/heic-sequence',
  'image/heif-sequence',
]);
const HEIC_EXT = /\.(heic|heif)$/i;

/**
 * Cheap, synchronous guess of whether a picked file is HEIC/HEIF.
 *
 * Browsers frequently report an EMPTY or unexpected MIME type for HEIC (iOS Safari,
 * some Android pickers), so the file extension is the reliable signal — we accept a
 * match on EITHER the MIME type or the `.heic`/`.heif` extension.
 */
export function looksLikeHeic(file: File): boolean {
  return HEIC_MIME.has((file.type || '').toLowerCase()) || HEIC_EXT.test(file.name);
}

/** Thrown when a HEIC file cannot be decoded/transcoded. Carries a user-safe message. */
export class HeicTranscodeError extends Error {
  constructor(
    message = "We couldn't read that HEIC photo. Try exporting it as JPEG and uploading again.",
  ) {
    super(message);
    this.name = 'HeicTranscodeError';
  }
}

/** `IMG_1234.heic` → `IMG_1234.jpg`; extension-less or odd names get a `.jpg`. */
function toJpegName(name: string): string {
  const base = (name || 'photo').replace(HEIC_EXT, '');
  return /\.jpe?g$/i.test(base) ? base : `${base}.jpg`;
}

/**
 * Transcode a HEIC/HEIF file to a JPEG {@link File}, decoding in the browser.
 *
 * Returns a NEW File (`image/jpeg`, `.jpg` name) whose bytes are the canonical bytes
 * for the rest of the flow — call this ONCE per picked file and reuse the result for
 * both the detect upload and the commit re-upload. Throws {@link HeicTranscodeError}
 * on any decode failure (never returns empty/partial bytes).
 */
export async function transcodeHeicToJpeg(file: File): Promise<File> {
  let out: Blob;
  try {
    // Dynamic import: the libheif-wasm decoder only loads when a HEIC is selected.
    const { heicTo } = await import('heic-to');
    out = await heicTo({ blob: file, type: 'image/jpeg', quality: JPEG_QUALITY });
  } catch {
    // Swallow the decoder's internal error (may reference wasm/worker internals) and
    // surface a clean, user-safe message. Nothing sensitive is logged.
    throw new HeicTranscodeError();
  }
  if (!out || out.size === 0) {
    throw new HeicTranscodeError();
  }
  return new File([out], toJpegName(file.name), {
    type: 'image/jpeg',
    lastModified: file.lastModified,
  });
}
