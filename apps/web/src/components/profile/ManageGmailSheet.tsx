'use client';

/**
 * ManageGmailSheet — deep-glass bottom sheet behind the Gmail card's "Manage".
 *
 * WIRED (real):
 *   - Re-sync now (POST /gmail/ingest/start → /review; 409-safe)
 *   - Change permissions (restarts the OAuth consent flow)
 *
 * HONEST-DISABLED:
 *   - Disconnect Gmail — no backend endpoint yet. The control is disabled and
 *     explains how to revoke access from Google in the meantime. Never fakes it.
 */

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { RotateCw, ShieldCheck, SlidersHorizontal } from 'lucide-react';
import { Btn, M, Sheet } from '@/components/ds';
import { startGmailConnect, startIngest } from '@/lib/api/gmail';

interface ManageGmailSheetProps {
  open: boolean;
  onClose: () => void;
  email?: string | null;
  lastSyncLabel?: string | null;
  itemCount?: number;
}

function ManageRow({
  icon,
  title,
  sub,
  right,
  onClick,
  disabled,
  first,
}: {
  icon: React.ReactNode;
  title: string;
  sub?: string;
  right?: React.ReactNode;
  onClick?: () => void;
  disabled?: boolean;
  first?: boolean;
}) {
  const inner = (
    <>
      <span
        className="flex shrink-0 items-center justify-center rounded-xl"
        style={{ width: 36, height: 36, background: 'rgba(255,255,255,0.08)', border: '1px solid rgba(255,255,255,0.09)', color: M.soft }}
      >
        {icon}
      </span>
      <span className="min-w-0 flex-1 text-left">
        <span className="block text-[14.5px] font-medium text-white">{title}</span>
        {sub && <span className="mt-0.5 block text-[12px] leading-snug text-white/[0.55]">{sub}</span>}
      </span>
      {right}
    </>
  );
  const style = { borderTop: first ? 'none' : '1px solid var(--tr-10)' } as React.CSSProperties;
  if (onClick) {
    return (
      <button
        type="button"
        onClick={onClick}
        disabled={disabled}
        className="flex w-full items-center gap-3 py-3.5 disabled:opacity-60"
        style={style}
      >
        {inner}
      </button>
    );
  }
  return (
    <div className="flex items-center gap-3 py-3.5" style={style}>
      {inner}
    </div>
  );
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

  const syncSub = [lastSyncLabel, itemCount != null ? `${itemCount} items` : null].filter(Boolean).join(' · ');

  return (
    <Sheet open={open} onClose={onClose} title="Gmail" sub={email ?? undefined}>
      <ManageRow
        first
        icon={<ShieldCheck size={16} />}
        title="Access"
        sub="Read-only · order receipts only"
        right={<span className="text-[12px] font-semibold" style={{ color: '#3ddf9e' }}>Active</span>}
      />
      <ManageRow
        icon={<RotateCw size={16} />}
        title="Last sync"
        sub={syncSub || 'Not synced yet'}
        onClick={handleResync}
        disabled={busy !== null}
        right={
          <span className="text-[12.5px] font-semibold text-white/[0.55]">
            {busy === 'resync' ? 'Syncing…' : 'Sync now'}
          </span>
        }
      />
      <ManageRow
        icon={<SlidersHorizontal size={16} />}
        title="Permissions"
        sub={busy === 'scope' ? 'Opening Google…' : 'Review what Tailor can read'}
        onClick={handleScope}
        disabled={busy !== null}
      />

      <div className="my-2 h-px" style={{ background: 'rgba(255,255,255,0.08)' }} aria-hidden />

      {/* HONEST-DISABLED: no disconnect endpoint yet. */}
      <button
        type="button"
        disabled
        title="Disconnect coming soon"
        className="flex w-full cursor-not-allowed items-center gap-3 py-3.5 opacity-60"
      >
        <span
          className="flex shrink-0 items-center justify-center rounded-xl"
          style={{ width: 36, height: 36, background: 'rgba(251,44,54,0.11)', border: '1px solid rgba(255,255,255,0.09)', color: '#ff8087' }}
        >
          <BanIcon />
        </span>
        <span className="min-w-0 flex-1 text-left">
          <span className="block text-[14.5px] font-medium" style={{ color: '#ff8087' }}>
            Disconnect Gmail
          </span>
          <span className="mt-0.5 block text-[12px] leading-snug text-white/[0.55]">
            Coming soon — for now, remove Tailor in your Google account permissions
          </span>
        </span>
      </button>

      <Btn variant="ghost" fullWidth size="md" className="mt-3" onClick={onClose}>
        Done
      </Btn>

      {note && (
        <p className="mb-0 mt-3 text-center text-[12.5px]" style={{ color: 'rgba(255,255,255,0.6)' }}>
          {note}
        </p>
      )}
    </Sheet>
  );
}

function BanIcon() {
  return (
    <svg width={16} height={16} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="10" />
      <path d="M4.9 4.9l14.2 14.2" />
    </svg>
  );
}
