'use client';

/**
 * AddItemDrawer — light bottom sheet (30px top radius, drag handle) with the three
 * ingestion options from the design: Take photo / Upload photo / Import from Gmail.
 *
 * Photo options no longer auto-stage anything: picked Files are stashed in
 * usePhotoPickStore (Files can't cross a navigation via URL) and we route to
 * /add-photo, where detection + region selection happen before anything is
 * committed. Gmail hands off to the caller (closet routes to /review, where the
 * scan CTA lives).
 */

import { Camera, ChevronRight, Image as ImageIcon } from 'lucide-react';
import { useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import { Sheet, GmailGlyph } from '@/components/ds';
import { usePhotoPickStore } from '@/stores/usePhotoPickStore';

interface AddItemDrawerProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onGmailClick: () => void;
}

const ACCEPTED_TYPES = ['image/jpeg', 'image/jpg', 'image/png', 'image/webp'];
const MAX_FILE_SIZE = 10 * 1024 * 1024; // 10MB — mirrors the backend cap
const MAX_FILES = 10;

interface OptRowProps {
  icon: React.ReactNode;
  title: string;
  sub: string;
  accent?: string;
  disabled?: boolean;
  onClick: () => void;
}

function OptRow({ icon, title, sub, accent = 'var(--brand-teal)', disabled, onClick }: OptRowProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className="flex w-full cursor-pointer items-center gap-3.5 rounded-[14px] border-none px-[18px] py-4 text-left transition-transform active:scale-[0.99] disabled:cursor-not-allowed disabled:opacity-50"
      style={{ background: 'var(--surface-sunken)' }}
    >
      <span
        className="flex shrink-0 items-center justify-center text-white"
        style={{ width: 46, height: 46, borderRadius: 12, background: accent }}
      >
        {icon}
      </span>
      <span className="flex-1">
        <span className="block text-[15.5px] font-semibold" style={{ color: 'var(--text-strong)' }}>
          {title}
        </span>
        <span className="block text-[13px]" style={{ color: 'var(--text-muted)' }}>
          {sub}
        </span>
      </span>
      <ChevronRight size={18} style={{ color: 'var(--text-muted)' }} />
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
      if (!ACCEPTED_TYPES.includes(file.type)) return 'Please choose JPEG, PNG, or WebP images.';
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
    <Sheet open={open} onClose={() => onOpenChange(false)} tone="light">
      <h3 className="m-0 mb-1 text-[21px] font-bold" style={{ color: 'var(--text-strong)' }}>
        Add to closet
      </h3>
      <p className="m-0 mb-[18px] text-sm" style={{ color: 'var(--text-muted)' }}>
        Tailor reads your clothes automatically.
      </p>

      {/* Hidden inputs: camera capture (single) + gallery picker (multiple). */}
      <input
        ref={cameraRef}
        type="file"
        accept={ACCEPTED_TYPES.join(',')}
        capture="environment"
        onChange={(e) => handleFiles(e.target.files)}
        className="hidden"
      />
      <input
        ref={galleryRef}
        type="file"
        accept={ACCEPTED_TYPES.join(',')}
        multiple
        onChange={(e) => handleFiles(e.target.files)}
        className="hidden"
      />

      {error && (
        <div
          className="mb-3 rounded-[10px] px-3 py-2.5 text-center text-[13.5px]"
          style={{ background: 'rgba(251,44,54,0.08)', border: '1px solid rgba(251,44,54,0.35)', color: 'var(--danger)' }}
        >
          {error}
        </div>
      )}

      <div className="flex flex-col gap-3">
        <OptRow
          icon={<Camera size={22} />}
          title="Take photo"
          sub="Snap an item or your outfit"
          onClick={() => cameraRef.current?.click()}
        />
        <OptRow
          icon={<ImageIcon size={22} />}
          title="Upload photo"
          sub="Choose from your library"
          accent="var(--teal-600)"
          onClick={() => galleryRef.current?.click()}
        />
        <OptRow
          icon={<GmailGlyph size={22} />}
          title="Import from Gmail"
          sub="Pull items from email receipts"
          accent="var(--teal-500)"
          onClick={() => {
            onOpenChange(false);
            onGmailClick();
          }}
        />
      </div>
    </Sheet>
  );
}
