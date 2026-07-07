'use client';

/**
 * Profile card for the Gmail connection — the two designed states:
 *   disconnected → Gmail glyph tile + copy + Connect (opens ConnectGmailModal)
 *   connected    → Active badge + email + last-sync line + Manage sheet
 *
 * Connection state is REAL (GET /gmail/oauth/status). The OAuth callback bounces
 * back here with ?gmail=connected|error, which opens the matching modal state.
 * This is connection plumbing ONLY — it never triggers ingestion by itself.
 */

import React, { useCallback, useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';

import { Btn, GmailGlyph, M } from '@/components/ds';
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
  if (mins < 60) return `synced ${mins}m ago`;
  const hours = Math.round(mins / 60);
  if (hours < 48) return `synced ${hours}h ago`;
  return `synced ${Math.round(hours / 24)}d ago`;
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

  const subline = connected
    ? [email ?? 'Your inbox', 'receipts only', lastSync].filter(Boolean).join(' · ')
    : 'Import order receipts automatically';

  return (
    <div style={{ ...M.glass(22), padding: '15px 16px' }} className="flex items-center gap-3">
      <span
        className="flex items-center justify-center"
        style={{
          width: 42,
          height: 42,
          borderRadius: 14,
          background: connected ? 'rgba(255,255,255,0.08)' : 'rgba(255,255,255,0.92)',
          border: '1px solid rgba(255,255,255,0.12)',
        }}
      >
        <GmailGlyph size={connected ? 19 : 22} />
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="text-[14.5px] font-semibold text-white">Gmail</span>
          {connected && (
            <span
              className="inline-flex items-center gap-1.5"
              style={{
                padding: '2.5px 9px',
                borderRadius: 999,
                background: 'rgba(10,207,131,0.13)',
                border: '1px solid rgba(10,207,131,0.35)',
                color: '#3ddf9e',
                fontSize: 10.5,
                fontWeight: 650,
              }}
            >
              <span style={{ width: 5, height: 5, borderRadius: '50%', background: '#3ddf9e' }} />
              Active
            </span>
          )}
        </div>
        <div className="mt-0.5 truncate text-[11.5px] text-white/[0.55]">{subline}</div>
      </div>
      {connected ? (
        <Btn variant="glass" size="sm" onClick={() => setManageOpen(true)}>
          Manage
        </Btn>
      ) : (
        <Btn
          variant="primary"
          size="sm"
          onClick={() => {
            setModalState('disconnected');
            setModalOpen(true);
          }}
        >
          Connect
        </Btn>
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
