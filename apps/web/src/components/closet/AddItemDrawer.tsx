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

import { AlertCircle, Camera, ChevronRight, FileX, Image as ImageIcon } from 'lucide-react';
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
  /** Amber warn treatment: tints the sub-copy + border and shows a trailing chip. */
  warn?: boolean;
  /** Trailing chip content (e.g. "Keep first 10"); replaces the chevron when set. */
  chip?: React.ReactNode;
  disabled?: boolean;
  onClick: () => void;
}

/** Deep-sheet option row — teal icon medallion, title + sub, chevron (or warn chip). */
function OptRow({ icon, title, sub, warn, chip, disabled, onClick }: OptRowProps) {
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
        borderColor: warn ? 'rgba(240,162,59,0.45)' : 'rgba(255,255,255,0.11)',
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
        <span className="block" style={{ color: warn ? '#f0b566' : M.faint, fontSize: 12.5, marginTop: 1 }}>
          {sub}
        </span>
      </span>
      {chip ? (
        <span
          className="inline-flex shrink-0 items-center font-semibold"
          style={{
            height: 26,
            padding: '0 12px',
            borderRadius: 999,
            fontSize: 12,
            background: 'rgba(240,162,59,0.14)',
            color: '#f0b566',
            border: '1px solid rgba(240,162,59,0.4)',
          }}
        >
          {chip}
        </span>
      ) : (
        <ChevronRight size={18} style={{ color: M.ghost }} />
      )}
    </button>
  );
}

/** One file rejected at validation, with the human reason surfaced in the banner. */
interface SkippedFile {
  name: string;
  reason: 'unsupported' | 'too-large';
}

const humanSize = MAX_FILE_SIZE / 1024 / 1024;

export function AddItemDrawer({ open, onOpenChange, onGmailClick }: AddItemDrawerProps) {
  const router = useRouter();
  // Non-blocking validation surface: the exact files we skipped (with reasons) and,
  // separately, whether the batch overflowed the 10-per-batch cap. Neither blocks the
  // valid files from proceeding — we keep the first MAX_FILES supported photos.
  const [skipped, setSkipped] = useState<SkippedFile[]>([]);
  const [overflow, setOverflow] = useState<number | null>(null); // picked count when > MAX_FILES
  const galleryRef = useRef<HTMLInputElement>(null);
  const cameraRef = useRef<HTMLInputElement>(null);

  const clearValidation = () => {
    setSkipped([]);
    setOverflow(null);
  };

  /**
   * Partition the picked files: collect per-file skip reasons (unsupported type /
   * over the size cap) and the supported remainder. Nothing is rejected wholesale —
   * supported photos still proceed, and the skipped list is surfaced inline.
   */
  const partition = (files: File[]): { keep: File[]; skipped: SkippedFile[] } => {
    const keep: File[] = [];
    const dropped: SkippedFile[] = [];
    for (const file of files) {
      if (!ACCEPTED_TYPES.includes(file.type) && !looksLikeHeic(file)) {
        dropped.push({ name: file.name, reason: 'unsupported' });
      } else if (file.size > MAX_FILE_SIZE) {
        dropped.push({ name: file.name, reason: 'too-large' });
      } else {
        keep.push(file);
      }
    }
    return { keep, skipped: dropped };
  };

  const handleFiles = (fileList: FileList | null) => {
    const files = Array.from(fileList ?? []);
    if (files.length === 0) return;
    if (galleryRef.current) galleryRef.current.value = '';
    if (cameraRef.current) cameraRef.current.value = '';

    const { keep, skipped: dropped } = partition(files);
    setSkipped(dropped);
    // Overflow chip: the amber "N selected — max 10 per batch" warning. We keep the first
    // MAX_FILES supported photos and proceed with those (never a hard block).
    setOverflow(keep.length > MAX_FILES ? keep.length : null);
    const batch = keep.slice(0, MAX_FILES);

    if (batch.length === 0) return; // everything was unsupported/too-large — surface + wait

    // Hand the Files to /add-photo in memory — detection and region selection
    // happen there; nothing is uploaded or staged from the drawer anymore.
    usePhotoPickStore.getState().setFiles(batch);
    onOpenChange(false);
    router.push('/add-photo');
  };

  // Banner copy: name the actual skipped files + their reasons, e.g.
  // "2 files skipped — IMG.tiff isn't supported and clip.mov is over 25MB."
  const skipReason = (s: SkippedFile) =>
    s.reason === 'unsupported' ? `isn't supported` : `is over ${humanSize}MB`;
  const skipBanner =
    skipped.length === 0
      ? null
      : skipped.length === 1
        ? `1 file skipped — ${skipped[0].name} ${skipReason(skipped[0])}.`
        : `${skipped.length} files skipped — ` +
          skipped
            .slice(0, 3)
            .map((s, i, arr) => `${s.name} ${skipReason(s)}${i < arr.length - 1 ? (i === arr.length - 2 ? ' and ' : ', ') : ''}`)
            .join('') +
          (skipped.length > 3 ? `, and ${skipped.length - 3} more.` : '.');

  return (
    <Sheet
      open={open}
      onClose={() => {
        clearValidation();
        onOpenChange(false);
      }}
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

      {/* Inline, non-blocking skip banner — names the actual files + reasons. Supported
          photos still proceed; this only reports what couldn't come along. */}
      {skipBanner && (
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
          <span style={{ flex: 1, color: '#fff', fontSize: 12.8, lineHeight: 1.45 }}>{skipBanner}</span>
        </div>
      )}

      {/* Amber over-cap notice — batch overflowed 10; we kept the first 10. */}
      {overflow != null && (
        <div
          className="mb-2.5 flex items-center gap-2.5"
          style={{
            padding: '11px 14px',
            borderRadius: 15,
            background: 'rgba(240,162,59,0.12)',
            border: '1px solid rgba(240,162,59,0.32)',
            backdropFilter: 'blur(12px)',
            WebkitBackdropFilter: 'blur(12px)',
          }}
          role="status"
        >
          <AlertCircle size={15} style={{ color: '#f0b566', flexShrink: 0 }} />
          <span style={{ flex: 1, color: '#fff', fontSize: 12.8, lineHeight: 1.45 }}>
            {overflow} selected — max {MAX_FILES} per batch. We kept the first {MAX_FILES}.
          </span>
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
          sub={overflow != null ? `${overflow} selected — max ${MAX_FILES} per batch` : 'Choose from your library'}
          warn={overflow != null}
          chip={overflow != null ? `Keep first ${MAX_FILES}` : undefined}
          onClick={() => galleryRef.current?.click()}
        />
        <OptRow
          icon={<GmailGlyph size={20} />}
          title="Import from Gmail"
          sub="Order receipts, read-only"
          onClick={() => {
            clearValidation();
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
