'use client';

/**
 * AddItemDrawer — unified deep-glass bottom sheet (§0 Sheet) hosting the three
 * ingestion options from the redesign: Take photo / Upload / Import from Gmail.
 *
 * Photo options no longer auto-stage anything: picked Files are stashed in
 * usePhotoPickStore (Files can't cross a navigation via URL) and we route to
 * /add-photo, where detection + region selection happen before anything is
 * committed. Gmail hands off to the caller (closet routes to /review, where the
 * scan CTA lives).
 */

import { Camera, ChevronRight, FileX, Image as ImageIcon } from 'lucide-react';
import { useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import { Sheet, GmailGlyph, M } from '@/components/ds';
import { usePhotoPickStore } from '@/stores/usePhotoPickStore';
import { looksLikeHeic } from '@/lib/image/heic';

interface AddItemDrawerProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onGmailClick: () => void;
}

const ACCEPTED_TYPES = ['image/jpeg', 'image/jpg', 'image/png', 'image/webp'];
// HEIC/HEIF are accepted here and transcoded to JPEG in /add-photo (PhotoIngestUpload);
// the drawer only stashes the originals, so it must not reject them. Extensions cover
// the common case of an empty/odd MIME on HEIC files.
const ACCEPT_ATTR = [...ACCEPTED_TYPES, 'image/heic', 'image/heif', '.heic', '.heif'].join(',');
const MAX_FILE_SIZE = 10 * 1024 * 1024; // 10MB — mirrors the backend cap
const MAX_FILES = 10;

interface OptRowProps {
  icon: React.ReactNode;
  title: string;
  sub: string;
  disabled?: boolean;
  onClick: () => void;
}

/** Deep-sheet option row — teal icon medallion, title + sub, chevron affordance. */
function OptRow({ icon, title, sub, disabled, onClick }: OptRowProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className="flex w-full cursor-pointer items-center gap-3.5 border text-left transition-transform active:scale-[0.99] disabled:cursor-not-allowed disabled:opacity-50"
      style={{
        padding: '14px 16px',
        borderRadius: 20,
        background: 'rgba(255,255,255,0.07)',
        borderColor: 'rgba(255,255,255,0.11)',
      }}
    >
      <span
        className="flex shrink-0 items-center justify-center text-white"
        style={{
          width: 44,
          height: 44,
          borderRadius: 15,
          background: 'linear-gradient(165deg, #10635c, #0a3633)',
          border: '1px solid rgba(255,255,255,0.16)',
        }}
      >
        {icon}
      </span>
      <span className="flex-1">
        <span className="block" style={{ color: '#fff', fontSize: 15, fontWeight: 600 }}>
          {title}
        </span>
        <span className="block" style={{ color: M.faint, fontSize: 12.5, marginTop: 1 }}>
          {sub}
        </span>
      </span>
      <ChevronRight size={18} style={{ color: M.ghost }} />
    </button>
  );
}

export function AddItemDrawer({ open, onOpenChange, onGmailClick }: AddItemDrawerProps) {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const galleryRef = useRef<HTMLInputElement>(null);
  const cameraRef = useRef<HTMLInputElement>(null);

  const validate = (files: File[]): string | null => {
    if (files.length > MAX_FILES) return `Up to ${MAX_FILES} photos at a time.`;
    for (const file of files) {
      if (!ACCEPTED_TYPES.includes(file.type) && !looksLikeHeic(file))
        return 'Please choose JPEG, PNG, WebP, or HEIC images.';
      if (file.size > MAX_FILE_SIZE) return `Each photo must be under ${MAX_FILE_SIZE / 1024 / 1024}MB.`;
    }
    return null;
  };

  const handleFiles = (fileList: FileList | null) => {
    const files = Array.from(fileList ?? []);
    if (files.length === 0) return;
    const validationError = validate(files);
    if (validationError) {
      setError(validationError);
      return;
    }
    setError(null);
    // Hand the Files to /add-photo in memory — detection and region selection
    // happen there; nothing is uploaded or staged from the drawer anymore.
    usePhotoPickStore.getState().setFiles(files);
    if (galleryRef.current) galleryRef.current.value = '';
    if (cameraRef.current) cameraRef.current.value = '';
    onOpenChange(false);
    router.push('/add-photo');
  };

  return (
    <Sheet
      open={open}
      onClose={() => onOpenChange(false)}
      tone="dark"
      title="Add to your closet"
      sub="Tailor reads your clothes automatically."
    >
      {/* Hidden inputs: camera capture (single) + gallery picker (multiple). */}
      <input
        ref={cameraRef}
        type="file"
        accept={ACCEPT_ATTR}
        capture="environment"
        onChange={(e) => handleFiles(e.target.files)}
        className="hidden"
      />
      <input
        ref={galleryRef}
        type="file"
        accept={ACCEPT_ATTR}
        multiple
        onChange={(e) => handleFiles(e.target.files)}
        className="hidden"
      />

      {/* Inline, non-blocking validation error (unsupported / too-large / too-many). */}
      {error && (
        <div
          className="mb-2.5 flex items-center gap-2.5"
          style={{
            padding: '11px 14px',
            borderRadius: 15,
            background: 'rgba(251,44,54,0.13)',
            border: '1px solid rgba(251,44,54,0.32)',
            backdropFilter: 'blur(12px)',
            WebkitBackdropFilter: 'blur(12px)',
          }}
          role="alert"
        >
          <FileX size={15} style={{ color: '#ff9096', flexShrink: 0 }} />
          <span style={{ flex: 1, color: '#fff', fontSize: 12.8, lineHeight: 1.45 }}>{error}</span>
        </div>
      )}

      <div className="flex flex-col" style={{ gap: 10 }}>
        <OptRow
          icon={<Camera size={20} />}
          title="Snap a photo"
          sub="An item, or your whole outfit"
          onClick={() => cameraRef.current?.click()}
        />
        <OptRow
          icon={<ImageIcon size={20} />}
          title="Upload from photos"
          sub="Choose from your library"
          onClick={() => galleryRef.current?.click()}
        />
        <OptRow
          icon={<GmailGlyph size={20} />}
          title="Import from Gmail"
          sub="Order receipts, read-only"
          onClick={() => {
            onOpenChange(false);
            onGmailClick();
          }}
        />
      </div>

      <div style={{ color: M.ghost, fontSize: 11.5, textAlign: 'center', marginTop: 12 }}>
        JPG, PNG, HEIC · up to {MAX_FILE_SIZE / 1024 / 1024} MB each · {MAX_FILES} per batch
      </div>
    </Sheet>
  );
}
