'use client';

/**
 * Profile card for the Gmail connection — the two designed states:
 *   disconnected → white Gmail tile + copy + Connect (opens ConnectGmailModal)
 *   connected    → green check + email + Active badge + last-sync line + Manage sheet
 *
 * Connection state is REAL (GET /gmail/oauth/status). The OAuth callback bounces
 * back here with ?gmail=connected|error, which opens the matching modal state.
 * This is connection plumbing ONLY — it never triggers ingestion by itself.
 */

import React, { useCallback, useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { Check } from 'lucide-react';

import { DSBadge, DSButton, GmailGlyph } from '@/components/ds';
import { ConnectGmailModal, type GmailModalState } from '@/components/auth/ConnectGmailModal';
import { ManageGmailSheet } from '@/components/profile/ManageGmailSheet';
import {
  fetchGmailConnectionStatus,
  getIngestCandidates,
  startGmailConnect,
  type GmailConnectionStatus,
} from '@/lib/api/gmail';

interface GmailConnectCardProps {
  email?: string | null;
  /** ISO timestamp of the last completed Gmail sync (from /auth/me), if any. */
  lastSyncAt?: string | null;
  itemCount?: number;
}

function timeAgoLabel(iso: string): string {
  const ms = Date.now() - new Date(iso).getTime();
  const mins = Math.max(1, Math.round(ms / 60000));
  if (mins < 60) return `last sync ${mins}m ago`;
  const hours = Math.round(mins / 60);
  if (hours < 48) return `last sync ${hours}h ago`;
  return `last sync ${Math.round(hours / 24)}d ago`;
}

export function GmailConnectCard({ email, lastSyncAt, itemCount }: GmailConnectCardProps) {
  const router = useRouter();
  const [status, setStatus] = useState<GmailConnectionStatus | null>(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [modalState, setModalState] = useState<GmailModalState>('disconnected');
  const [manageOpen, setManageOpen] = useState(false);
  const [reviewCount, setReviewCount] = useState<number | undefined>(undefined);

  const refresh = useCallback(async () => {
    try {
      setStatus(await fetchGmailConnectionStatus());
    } catch {
      // Non-fatal: leave status unknown; the connect button still works.
      setStatus(null);
    }
  }, []);

  useEffect(() => {
    refresh();
    // Surface the coarse outcome flag set by the /gmail/oauth/callback handler.
    const params = new URLSearchParams(window.location.search);
    const flag = params.get('gmail');
    if (flag === 'error') {
      setModalState('error');
      setModalOpen(true);
    } else if (flag === 'connected') {
      setModalState('connected');
      setModalOpen(true);
      // Pending candidates give the "Review N items" copy its number.
      getIngestCandidates()
        .then((cands) => setReviewCount(cands.length))
        .catch(() => setReviewCount(undefined));
    }
  }, [refresh]);

  const handleConnect = async () => {
    setModalState('connecting');
    try {
      await startGmailConnect(); // full-page redirect to Google on success
    } catch {
      setModalState('error');
    }
  };

  const connected = status?.connected ?? false;
  const lastSync = lastSyncAt ? timeAgoLabel(lastSyncAt) : null;

  return (
    <div
      className="rounded-[20px] p-5"
      style={{
        background: 'var(--tr-10)',
        border: '1px solid var(--tr-20)',
        backdropFilter: 'blur(12px)',
        WebkitBackdropFilter: 'blur(12px)',
      }}
    >
      {connected ? (
        <>
          <div className="flex items-center gap-3">
            <span
              className="flex items-center justify-center rounded-xl"
              style={{ width: 44, height: 44, background: 'rgba(10,207,131,0.18)', color: 'var(--success)' }}
            >
              <Check size={22} strokeWidth={2.4} />
            </span>
            <div className="flex-1">
              <div className="text-[16px] font-bold text-white">Gmail connected</div>
              <div className="text-[13px] text-white/60">{email ?? 'Your inbox'}</div>
            </div>
            <DSBadge variant="outline" style={{ color: 'var(--mint)', borderColor: 'rgba(75,226,214,0.4)' }}>
              Active
            </DSBadge>
          </div>
          <div className="my-4 h-px" style={{ background: 'var(--tr-10)' }} aria-hidden />
          <div className="flex items-center justify-between">
            <div className="text-[13px] text-white/70">
              Reads order receipts{lastSync ? ` · ${lastSync}` : ''}
            </div>
            <button
              type="button"
              onClick={() => setManageOpen(true)}
              className="text-[13px] font-semibold text-white/60 hover:text-white"
            >
              Manage
            </button>
          </div>
        </>
      ) : (
        <>
          <div className="mb-3.5 flex items-center gap-3">
            <span
              className="flex items-center justify-center rounded-xl"
              style={{ width: 44, height: 44, background: 'rgba(255,255,255,0.92)' }}
            >
              <GmailGlyph size={24} />
            </span>
            <div>
              <div className="text-[16px] font-bold text-white">Connect Gmail</div>
              <div className="text-[13px] text-white/60">Auto-import from receipts</div>
            </div>
          </div>
          <p className="m-0 mb-4 text-[13.5px] leading-relaxed text-white/70">
            Let Tailor read your order emails and build your closet for you.
          </p>
          <DSButton
            variant="light"
            fullWidth
            pill
            style={{ height: 46 }}
            onClick={() => {
              setModalState('disconnected');
              setModalOpen(true);
            }}
          >
            Connect
          </DSButton>
        </>
      )}

      <ConnectGmailModal
        open={modalOpen}
        state={modalState}
        reviewCount={reviewCount}
        onClose={() => setModalOpen(false)}
        onConnect={handleConnect}
        onReview={() => {
          setModalOpen(false);
          router.push('/review');
        }}
      />

      <ManageGmailSheet
        open={manageOpen}
        onClose={() => setManageOpen(false)}
        email={email}
        lastSyncLabel={lastSync}
        itemCount={itemCount}
      />
    </div>
  );
}
