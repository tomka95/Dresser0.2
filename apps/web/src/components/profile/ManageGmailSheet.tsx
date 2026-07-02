'use client';

/**
 * ManageGmailSheet — dark bottom sheet behind the Gmail card's "Manage" action.
 * Re-sync (REAL: POST /gmail/ingest/start → /review) · Change permissions
 * (REAL: restarts the OAuth consent flow) · Disconnect (no backend endpoint yet).
 */

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { Check, ChevronRight, RotateCw, SlidersHorizontal } from 'lucide-react';
import { Sheet } from '@/components/ds';
import { startGmailConnect, startIngest } from '@/lib/api/gmail';

interface ManageGmailSheetProps {
  open: boolean;
  onClose: () => void;
  email?: string | null;
  lastSyncLabel?: string | null;
  itemCount?: number;
}

export function ManageGmailSheet({ open, onClose, email, lastSyncLabel, itemCount }: ManageGmailSheetProps) {
  const router = useRouter();
  const [busy, setBusy] = useState<'resync' | 'scope' | null>(null);
  const [note, setNote] = useState<string | null>(null);

  const handleResync = async () => {
    if (busy) return;
    setBusy('resync');
    setNote(null);
    try {
      await startIngest(); // 409-safe: backend reuses a running sync
      onClose();
      router.push('/review');
    } catch (err) {
      setNote(err instanceof Error ? err.message : 'Could not start a sync.');
    } finally {
      setBusy(null);
    }
  };

  const handleScope = async () => {
    if (busy) return;
    setBusy('scope');
    setNote(null);
    try {
      await startGmailConnect(); // full-page redirect to Google consent
    } catch (err) {
      setNote(err instanceof Error ? err.message : 'Could not open Google permissions.');
      setBusy(null);
    }
  };

  const subline = [lastSyncLabel, itemCount != null ? `${itemCount} items` : null]
    .filter(Boolean)
    .join(' · ');

  return (
    <Sheet open={open} onClose={onClose} title="Manage Gmail">
      <div className="flex items-center gap-3 px-0.5 pb-4 pt-1">
        <span
          className="flex items-center justify-center rounded-[11px]"
          style={{ width: 42, height: 42, background: 'rgba(10,207,131,0.18)', color: 'var(--success)' }}
        >
          <Check size={20} strokeWidth={2.4} />
        </span>
        <div className="flex-1">
          <div className="text-[15.5px] font-semibold text-white">{email ?? 'Gmail account'}</div>
          {subline && (
            <div className="text-[12.5px]" style={{ color: 'rgba(255,255,255,0.5)' }}>
              {subline}
            </div>
          )}
        </div>
      </div>

      {(
        [
          { id: 'resync', label: busy === 'resync' ? 'Starting sync…' : 'Re-sync now', icon: <RotateCw size={18} />, onClick: handleResync },
          { id: 'scope', label: busy === 'scope' ? 'Opening Google…' : 'Change permissions', icon: <SlidersHorizontal size={18} />, onClick: handleScope },
        ] as const
      ).map((row) => (
        <button
          key={row.id}
          type="button"
          onClick={row.onClick}
          disabled={busy !== null}
          className="flex w-full cursor-pointer items-center gap-3 px-1 py-3.5 text-left disabled:opacity-60"
          style={{ borderTop: '1px solid var(--tr-10)' }}
        >
          <span style={{ color: 'rgba(255,255,255,0.8)' }}>{row.icon}</span>
          <span className="flex-1 text-[15px] text-white">{row.label}</span>
          <ChevronRight size={17} style={{ color: 'rgba(255,255,255,0.5)' }} />
        </button>
      ))}

      <button
        type="button"
        onClick={() =>
          setNote('Disconnect is coming soon — for now, remove Tailor from your Google account permissions.')
        }
        className="mt-4 h-[50px] w-full cursor-pointer rounded-full text-[15px] font-semibold"
        style={{
          border: '1px solid rgba(251,44,54,0.4)',
          background: 'rgba(251,44,54,0.12)',
          color: '#ff6b6b',
          fontFamily: 'var(--font-sans)',
        }}
      >
        Disconnect Gmail
      </button>

      {note && (
        <p className="mb-0 mt-3 text-center text-[12.5px]" style={{ color: 'rgba(255,255,255,0.6)' }}>
          {note}
        </p>
      )}
    </Sheet>
  );
}
