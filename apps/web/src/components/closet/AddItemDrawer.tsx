'use client';

import React, { useRef, useState } from 'react';
import { Camera, ChevronRight, Image as ImageIcon } from 'lucide-react';
import * as Dialog from '@radix-ui/react-dialog';
import { uploadOutfitImage } from '@/lib/api/outfit';
import { useClosetStore } from '@/stores/useClosetStore';

interface AddItemDrawerProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onGmailClick: () => void;
}

const ACCEPTED_TYPES = ['image/jpeg', 'image/jpg', 'image/png', 'image/webp'];
const MAX_FILE_SIZE = 10 * 1024 * 1024; // 10MB

/** Gmail glyph (envelope). */
function GmailGlyph() {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none">
      <path
        d="M2 6.5A1.5 1.5 0 0 1 3.5 5h17A1.5 1.5 0 0 1 22 6.5v11a1.5 1.5 0 0 1-1.5 1.5h-17A1.5 1.5 0 0 1 2 17.5z"
        fill="#fff"
      />
      <path d="M3 6.5l9 6 9-6" stroke="#ea4335" strokeWidth="1.8" fill="none" />
      <path d="M22 6.7V17.5a1.5 1.5 0 0 1-1.5 1.5H18V9.2l4-2.5z" fill="#34a853" />
      <path d="M2 6.7V17.5A1.5 1.5 0 0 0 3.5 19H6V9.2L2 6.7z" fill="#4285f4" />
    </svg>
  );
}

interface OptionRowProps {
  icon: React.ReactNode;
  chipBg: string;
  title: string;
  sub: string;
  onClick: () => void;
  disabled?: boolean;
}

function OptionRow({ icon, chipBg, title, sub, onClick, disabled }: OptionRowProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className="flex items-center gap-3.5 w-full text-left active:scale-[0.99] transition-transform disabled:opacity-50"
      style={{ background: 'var(--surface-sunken)', borderRadius: 14, padding: 12 }}
    >
      <span
        className="flex items-center justify-center shrink-0"
        style={{ width: 46, height: 46, borderRadius: 14, background: chipBg }}
      >
        {icon}
      </span>
      <span className="flex-1 min-w-0">
        <span className="block" style={{ color: 'var(--text-strong)', fontSize: 15.5, fontWeight: 600 }}>
          {title}
        </span>
        <span className="block" style={{ color: 'var(--text-muted)', fontSize: 13 }}>
          {sub}
        </span>
      </span>
      <ChevronRight size={20} style={{ color: 'var(--text-muted)' }} className="shrink-0" />
    </button>
  );
}

/** Light bottom sheet for adding a closet item (camera, upload, or Gmail import). */
export function AddItemDrawer({ open, onOpenChange, onGmailClick }: AddItemDrawerProps) {
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const uploadInputRef = useRef<HTMLInputElement>(null);
  const cameraInputRef = useRef<HTMLInputElement>(null);

  const validateFile = (file: File): string | null => {
    if (!ACCEPTED_TYPES.includes(file.type)) {
      return 'Please choose a JPEG, PNG, or WebP image.';
    }
    if (file.size > MAX_FILE_SIZE) {
      return 'Image must be 10MB or smaller.';
    }
    return null;
  };

  const handleFile = async (file: File) => {
    const validationError = validateFile(file);
    if (validationError) {
      setError(validationError);
      return;
    }
    setError(null);
    setUploading(true);
    try {
      await uploadOutfitImage(file);
      await useClosetStore.getState().fetchItems();
      onOpenChange(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Upload failed. Please try again.');
    } finally {
      setUploading(false);
      if (uploadInputRef.current) uploadInputRef.current.value = '';
      if (cameraInputRef.current) cameraInputRef.current.value = '';
    }
  };

  const onInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) handleFile(file);
  };

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-[90]" style={{ background: 'rgba(0,0,0,0.5)' }} />
        <Dialog.Content
          className="fixed bottom-0 left-1/2 -translate-x-1/2 w-full max-w-[430px] z-[95] outline-none"
          onInteractOutside={(e) => uploading && e.preventDefault()}
          aria-describedby={undefined}
        >
          <div
            style={{
              background: 'var(--surface-card)',
              borderTopLeftRadius: 30,
              borderTopRightRadius: 30,
              padding: '20px 24px 34px',
            }}
          >
            {/* drag handle */}
            <div
              className="mx-auto mb-4"
              style={{ width: 40, height: 4, borderRadius: 999, background: 'var(--grey)' }}
            />

            <Dialog.Title className="m-0" style={{ color: 'var(--text-strong)', fontSize: 21, fontWeight: 700 }}>
              Add to closet
            </Dialog.Title>
            <p className="m-0 mt-1 mb-5" style={{ color: 'var(--text-muted)', fontSize: 14 }}>
              Tailor reads your clothes automatically.
            </p>

            {/* hidden inputs */}
            <input
              ref={cameraInputRef}
              type="file"
              accept={ACCEPTED_TYPES.join(',')}
              capture="environment"
              onChange={onInputChange}
              className="hidden"
            />
            <input
              ref={uploadInputRef}
              type="file"
              accept={ACCEPTED_TYPES.join(',')}
              onChange={onInputChange}
              className="hidden"
            />

            {error && (
              <div className="mb-3 text-center" style={{ color: 'var(--danger)', fontSize: 13.5, fontWeight: 500 }}>
                {error}
              </div>
            )}

            {uploading && (
              <div className="mb-3 flex items-center justify-center gap-2" style={{ color: 'var(--text-body)' }}>
                <span
                  style={{
                    width: 18,
                    height: 18,
                    borderRadius: '50%',
                    border: '2px solid var(--surface-sunken)',
                    borderTop: '2px solid var(--brand-teal)',
                    animation: 'tailor-spin 0.9s linear infinite',
                  }}
                />
                <span style={{ fontSize: 14 }}>Reading your item…</span>
              </div>
            )}

            <div className="flex flex-col gap-3">
              <OptionRow
                icon={<Camera size={22} color="#fff" />}
                chipBg="var(--brand-teal)"
                title="Take photo"
                sub="Snap an item or your outfit"
                onClick={() => !uploading && cameraInputRef.current?.click()}
                disabled={uploading}
              />
              <OptionRow
                icon={<ImageIcon size={22} color="#fff" />}
                chipBg="var(--teal-600)"
                title="Upload photo"
                sub="Choose from your library"
                onClick={() => !uploading && uploadInputRef.current?.click()}
                disabled={uploading}
              />
              <OptionRow
                icon={<GmailGlyph />}
                chipBg="var(--teal-500)"
                title="Import from Gmail"
                sub="Pull items from email receipts"
                onClick={() => {
                  onGmailClick();
                  onOpenChange(false);
                }}
                disabled={uploading}
              />
            </div>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
