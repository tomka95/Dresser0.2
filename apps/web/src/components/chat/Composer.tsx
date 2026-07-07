'use client';

import { useRef, useState } from 'react';
import { ImagePlus, Send, Shirt, X } from 'lucide-react';

import { Sheet } from '@/components/ds';
import { ItemImage } from '@/components/ui/ItemImage';

import type { ClosetItemLite, PendingImage } from './types';

/**
 * The composer: attachment tray (HEIC transcode spinner → image thumb, closet
 * thumbs, each removable) + input row (photo attach · closet attach Sheet · text
 * · mint send when armed). The send disc lights mint only when there's something
 * to send, matching the design. All attach/transcode logic stays in the parent —
 * this is presentational, driven by props.
 */
export function Composer({
  draft,
  onDraftChange,
  onSend,
  streaming,
  disabled = false,
  incognito = false,
  pendingImage,
  attachingImage,
  attachedItems,
  onAttachFile,
  onRemoveImage,
  onRemoveItem,
  closetItems,
  attachedItemIds,
  onToggleItem,
}: {
  draft: string;
  onDraftChange: (v: string) => void;
  onSend: () => void;
  streaming: boolean;
  disabled?: boolean;
  incognito?: boolean;
  pendingImage: PendingImage | null;
  attachingImage: boolean;
  attachedItems: ClosetItemLite[];
  onAttachFile: (file: File) => void;
  onRemoveImage: () => void;
  onRemoveItem: (id: string) => void;
  closetItems: ClosetItemLite[];
  attachedItemIds: string[];
  onToggleItem: (id: string) => void;
}) {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [pickerOpen, setPickerOpen] = useState(false);

  const armed = draft.trim().length > 0 || !!pendingImage || attachedItems.length > 0;
  const inputsDisabled = streaming || disabled;
  const hasTray = pendingImage != null || attachingImage || attachedItems.length > 0;

  return (
    <div style={{ padding: '10px 16px 14px' }}>
      {/* Attachment tray */}
      {hasTray && (
        <div className="mb-2 flex items-center gap-2 overflow-x-auto scrollbar-hide">
          {attachingImage && !pendingImage && (
            <div
              className="flex shrink-0 items-center justify-center rounded-[10px]"
              style={{ width: 44, height: 44, border: '1px solid var(--tr-20)' }}
            >
              <span
                className="inline-block h-4 w-4 animate-spin rounded-full"
                style={{ border: '2px solid var(--tr-20)', borderTopColor: 'var(--mint)' }}
                aria-label="Preparing photo"
              />
            </div>
          )}
          {pendingImage && (
            <div
              className="relative flex shrink-0 items-center justify-center overflow-hidden rounded-[10px]"
              style={{ width: 44, height: 44, border: '1px solid var(--tr-20)' }}
            >
              {pendingImage.previewUrl ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={pendingImage.previewUrl}
                  alt="Attached"
                  className="h-full w-full object-cover"
                />
              ) : (
                // Decode failed — bytes still send; show a neutral photo glyph.
                <ImagePlus size={18} style={{ color: 'rgba(255,255,255,0.5)' }} />
              )}
              <button
                type="button"
                aria-label="Remove image"
                onClick={onRemoveImage}
                className="absolute right-0 top-0 flex h-4 w-4 items-center justify-center rounded-bl bg-black/70 text-[10px] text-white"
              >
                ×
              </button>
            </div>
          )}
          {attachedItems.map((item) => (
            <div
              key={item.id}
              className="relative shrink-0 overflow-hidden rounded-[10px]"
              style={{ width: 44, height: 44, border: '1px solid var(--tr-20)' }}
            >
              <ItemImage src={item.imageUrl ?? undefined} alt={item.name} fit="cover" />
              <button
                type="button"
                aria-label={`Remove ${item.name}`}
                onClick={() => onRemoveItem(item.id)}
                className="absolute right-0 top-0 flex h-4 w-4 items-center justify-center rounded-bl bg-black/70 text-[10px] text-white"
              >
                ×
              </button>
            </div>
          ))}
        </div>
      )}

      <input
        ref={fileInputRef}
        type="file"
        accept="image/jpeg,image/png,image/webp,image/heic,image/heif,.heic,.heif"
        className="hidden"
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (file) onAttachFile(file);
          e.target.value = '';
        }}
      />

      <form
        onSubmit={(e) => {
          e.preventDefault();
          onSend();
        }}
        className="flex items-center rounded-full"
        style={{
          gap: 9,
          padding: '7px 7px 7px 8px',
          background: 'linear-gradient(180deg, rgba(16,32,31,0.82), rgba(9,20,20,0.88))',
          border: incognito
            ? '1px solid rgba(150,120,230,0.4)'
            : '1px solid rgba(255,255,255,0.12)',
          backdropFilter: 'blur(28px) saturate(160%)',
          WebkitBackdropFilter: 'blur(28px) saturate(160%)',
          opacity: disabled ? 0.55 : 1,
        }}
      >
        <button
          type="button"
          aria-label="Attach a photo"
          onClick={() => fileInputRef.current?.click()}
          disabled={inputsDisabled}
          className="flex shrink-0 items-center justify-center rounded-full text-white/75 disabled:opacity-40"
          style={{ width: 38, height: 38, background: 'rgba(255,255,255,0.07)' }}
        >
          <ImagePlus size={18} />
        </button>
        <button
          type="button"
          aria-label="Attach from closet"
          onClick={() => setPickerOpen(true)}
          disabled={inputsDisabled}
          className="flex shrink-0 items-center justify-center rounded-full text-white/75 disabled:opacity-40"
          style={{ width: 38, height: 38, background: 'rgba(255,255,255,0.07)' }}
        >
          <Shirt size={18} />
        </button>
        <input
          value={draft}
          onChange={(e) => onDraftChange(e.target.value)}
          placeholder={
            disabled
              ? 'Sends when you’re back online…'
              : streaming
                ? 'Stylist is replying…'
                : 'Ask about your closet…'
          }
          disabled={inputsDisabled}
          className="min-w-0 flex-1 border-none bg-transparent text-white outline-none placeholder:text-white/40"
          style={{ fontSize: 14.5, fontFamily: 'var(--font-sans)' }}
        />
        <button
          type="submit"
          aria-label="Send"
          disabled={inputsDisabled || !armed}
          className="flex shrink-0 items-center justify-center rounded-full transition-transform active:scale-90 disabled:cursor-not-allowed"
          style={{
            width: 40,
            height: 40,
            background: armed
              ? 'linear-gradient(165deg, #52e8dc, #2cc9bc)'
              : 'rgba(255,255,255,0.08)',
            color: armed ? '#06302d' : 'rgba(255,255,255,0.36)',
            boxShadow: armed ? '0 8px 20px -6px rgba(75,226,214,0.5)' : 'none',
          }}
        >
          <Send size={17} />
        </button>
      </form>

      {/* Closet-item picker (max 3) */}
      <Sheet
        open={pickerOpen}
        onClose={() => setPickerOpen(false)}
        title="Attach from closet"
        sub="Pick up to 3 items to ask about"
      >
        <div className="grid max-h-[50vh] grid-cols-3 gap-2 overflow-y-auto p-1">
          {closetItems.length === 0 && (
            <div className="col-span-3 py-6 text-center text-[13px] text-white/50">
              Your closet is empty — add items first.
            </div>
          )}
          {closetItems.map((item) => {
            const selected = attachedItemIds.includes(item.id);
            return (
              <button
                key={item.id}
                type="button"
                onClick={() => onToggleItem(item.id)}
                className="overflow-hidden rounded-[12px] text-left"
                style={{ border: selected ? '2px solid var(--mint)' : '1px solid var(--tr-20)' }}
              >
                <div style={{ aspectRatio: '3/4' }}>
                  <ItemImage src={item.imageUrl ?? undefined} alt={item.name} fit="cover" />
                </div>
                <div className="truncate px-1.5 py-1 text-[11px] text-white/80">{item.name}</div>
              </button>
            );
          })}
        </div>
        <button
          type="button"
          onClick={() => setPickerOpen(false)}
          className="mt-3 w-full rounded-full py-3 text-[14px] font-semibold"
          style={{ background: 'var(--mint)', color: 'var(--brand-teal)' }}
        >
          Done
        </button>
      </Sheet>
    </div>
  );
}
