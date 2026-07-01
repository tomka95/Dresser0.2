'use client';

/**
 * PhotoIngestUpload — mobile-web entry for photo -> closet ingestion (Wave 1).
 *
 * Reuses the OutfitImageUpload patterns (client-side type/size validation, previews,
 * disabled-while-busy) but selects MULTIPLE photos and posts them to the photo-ingest
 * source. On success it routes to the existing /review swipe deck, where the staged
 * garment candidates appear exactly like Gmail ones.
 *
 * Photo selection on device: a plain <input type="file" accept="image/*" multiple>
 * opens the OS picker (camera + gallery on iOS/Android browsers); a second
 * capture="environment" input is the explicit "Take photo" affordance.
 */
import { useCallback, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import { Camera, ImagePlus, X } from 'lucide-react';

import { startPhotoIngest } from '@/lib/api/gmail';
import { useClosetStore } from '@/stores/useClosetStore';

type State = 'idle' | 'uploading' | 'error';

const MAX_FILE_SIZE = 10 * 1024 * 1024; // 10MB — mirrors the backend cap
const MAX_FILES = 10;
const ACCEPTED = ['image/jpeg', 'image/jpg', 'image/png', 'image/webp'];

interface Picked {
  file: File;
  previewUrl: string;
}

export function PhotoIngestUpload() {
  const router = useRouter();
  const [picked, setPicked] = useState<Picked[]>([]);
  const [state, setState] = useState<State>('idle');
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const galleryRef = useRef<HTMLInputElement>(null);
  const cameraRef = useRef<HTMLInputElement>(null);

  const busy = state === 'uploading';

  const addFiles = useCallback(
    (files: FileList | null) => {
      if (!files || files.length === 0) return;
      setError(null);
      setNotice(null);
      setPicked((prev) => {
        const next = [...prev];
        for (const file of Array.from(files)) {
          if (next.length >= MAX_FILES) {
            setNotice(`Up to ${MAX_FILES} photos at a time.`);
            break;
          }
          if (!ACCEPTED.includes(file.type)) {
            setError('Please choose JPEG, PNG, or WebP images.');
            continue;
          }
          if (file.size > MAX_FILE_SIZE) {
            setError(`Each photo must be under ${MAX_FILE_SIZE / 1024 / 1024}MB.`);
            continue;
          }
          next.push({ file, previewUrl: URL.createObjectURL(file) });
        }
        return next;
      });
    },
    [],
  );

  const removeAt = useCallback((i: number) => {
    setPicked((prev) => {
      const target = prev[i];
      if (target) URL.revokeObjectURL(target.previewUrl);
      return prev.filter((_, idx) => idx !== i);
    });
  }, []);

  const handleSubmit = useCallback(async () => {
    if (picked.length === 0 || busy) return;
    setState('uploading');
    setError(null);
    setNotice(null);
    try {
      const res = await startPhotoIngest(picked.map((p) => p.file));
      // Closet may change after confirm; invalidate so it refetches later.
      useClosetStore.getState().invalidate?.();
      if (res.staged > 0) {
        // Release the preview object-URLs before navigating — otherwise they leak as
        // 0-byte blob: entries that outlive this screen. The deck renders the server's
        // image_url directly (no blob), so nothing here needs them anymore.
        picked.forEach((p) => URL.revokeObjectURL(p.previewUrl));
        // Scope the deck to THIS run so it shows only the photo's garments — not stale
        // pending candidates from an earlier run.
        router.push(`/review?sync_id=${encodeURIComponent(res.sync_id)}`);
        return;
      }
      // Nothing to review — surface why (held for multi-person / dup / no clothing).
      setState('idle');
      setNotice(res.message ?? 'No new items to review.');
      picked.forEach((p) => URL.revokeObjectURL(p.previewUrl));
      setPicked([]);
    } catch (err) {
      setState('error');
      setError(err instanceof Error ? err.message : 'Failed to process photos.');
    }
  }, [picked, busy, router]);

  return (
    <div className="flex flex-col gap-4">
      {error && (
        <div className="rounded-lg border p-3 text-sm" style={{ borderColor: 'var(--danger)', color: 'var(--danger)' }}>
          {error}
        </div>
      )}
      {notice && (
        <div className="rounded-lg px-3 py-2 text-[13px]" style={{ background: 'var(--tr-10)', color: 'rgba(255,255,255,0.75)' }}>
          {notice}
        </div>
      )}

      {/* Hidden inputs: gallery (multiple) + camera (capture). */}
      <input
        ref={galleryRef}
        type="file"
        accept="image/*"
        multiple
        className="hidden"
        onChange={(e) => {
          addFiles(e.target.files);
          e.currentTarget.value = '';
        }}
      />
      <input
        ref={cameraRef}
        type="file"
        accept="image/*"
        capture="environment"
        className="hidden"
        onChange={(e) => {
          addFiles(e.target.files);
          e.currentTarget.value = '';
        }}
      />

      <div className="flex gap-3">
        <button
          type="button"
          onClick={() => galleryRef.current?.click()}
          disabled={busy}
          className="flex flex-1 items-center justify-center gap-2 rounded-xl py-3 text-[14px] font-medium disabled:opacity-50"
          style={{ background: 'var(--tr-10)', border: '1px solid var(--tr-20)', color: 'white' }}
        >
          <ImagePlus size={18} /> Choose photos
        </button>
        <button
          type="button"
          onClick={() => cameraRef.current?.click()}
          disabled={busy}
          className="flex flex-1 items-center justify-center gap-2 rounded-xl py-3 text-[14px] font-medium disabled:opacity-50"
          style={{ background: 'var(--tr-10)', border: '1px solid var(--tr-20)', color: 'white' }}
        >
          <Camera size={18} /> Take photo
        </button>
      </div>

      {picked.length > 0 && (
        <div className="grid grid-cols-3 gap-2">
          {picked.map((p, i) => (
            <div key={p.previewUrl} className="relative aspect-square overflow-hidden rounded-lg" style={{ background: '#333' }}>
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={p.previewUrl} alt={`Selected ${i + 1}`} className="h-full w-full object-cover" />
              {!busy && (
                <button
                  type="button"
                  onClick={() => removeAt(i)}
                  aria-label="Remove"
                  className="absolute right-1 top-1 flex h-6 w-6 items-center justify-center rounded-full"
                  style={{ background: 'rgba(0,0,0,0.6)', color: 'white' }}
                >
                  <X size={14} />
                </button>
              )}
            </div>
          ))}
        </div>
      )}

      <button
        type="button"
        onClick={handleSubmit}
        disabled={picked.length === 0 || busy}
        className="rounded-xl py-3.5 text-[15px] font-semibold disabled:opacity-50"
        style={{ background: 'var(--mint)', color: 'var(--brand-teal)' }}
      >
        {busy
          ? 'Finding your clothes…'
          : picked.length > 0
          ? `Add ${picked.length} photo${picked.length > 1 ? 's' : ''}`
          : 'Select photos to continue'}
      </button>
      <p className="text-center text-[12px]" style={{ color: 'rgba(255,255,255,0.5)' }}>
        Use a photo of just yourself. JPEG, PNG, or WebP, up to {MAX_FILE_SIZE / 1024 / 1024}MB each.
      </p>
    </div>
  );
}
