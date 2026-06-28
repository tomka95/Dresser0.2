'use client';

import React, { useCallback, useEffect, useState } from 'react';
import { Check } from 'lucide-react';
import { useSearchParams } from 'next/navigation';

import { LightButton } from '@/components/ui/LightButton';
import { DarkBadge } from '@/components/ui/DarkBadge';
import { ConnectGmailModal, type ConnectGmailStatus } from '@/components/auth/ConnectGmailModal';
import {
  fetchGmailConnectionStatus,
  startGmailConnect,
  type GmailConnectionStatus,
} from '@/lib/api/gmail';

/** Gmail glyph (envelope). */
function GmailGlyph({ size = 22 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none">
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

/**
 * Profile card for the Gmail connection. Reads real connected state from the
 * backend and lets the user start the connect flow via ConnectGmailModal.
 * Connection plumbing only — never triggers ingestion.
 */
export function GmailConnectCard() {
  const searchParams = useSearchParams();
  const [status, setStatus] = useState<GmailConnectionStatus | null>(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [modalStatus, setModalStatus] = useState<ConnectGmailStatus>('disconnected');

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
  }, [refresh]);

  // Surface the coarse outcome flag set by the /gmail/oauth/callback handler.
  useEffect(() => {
    if (searchParams.get('gmail') === 'error') {
      setModalStatus('error');
      setModalOpen(true);
    }
  }, [searchParams]);

  const handleConnect = async () => {
    setModalStatus('connecting');
    try {
      await startGmailConnect(); // full-page redirect to Google on success
    } catch {
      setModalStatus('error');
    }
  };

  const connected = status?.connected ?? false;

  return (
    <div
      style={{
        borderRadius: 20,
        background: 'var(--tr-10)',
        border: '1px solid var(--tr-20)',
        backdropFilter: 'blur(12px)',
        WebkitBackdropFilter: 'blur(12px)',
        padding: 20,
      }}
    >
      {connected ? (
        <>
          <div className="flex items-center gap-3.5">
            <span
              className="flex items-center justify-center shrink-0"
              style={{ width: 46, height: 46, borderRadius: 14, background: 'rgba(10,207,131,0.15)', color: 'var(--success)' }}
            >
              <Check size={22} />
            </span>
            <div className="flex-1 min-w-0">
              <div className="text-white font-semibold text-[15.5px]">Gmail connected</div>
              <div className="truncate" style={{ color: 'rgba(255,255,255,0.6)', fontSize: 13 }}>
                {status?.scope ? 'Reads order receipts' : 'Auto-import active'}
              </div>
            </div>
            <DarkBadge variant="outline" style={{ color: 'var(--mint)', borderColor: 'var(--mint)' }}>
              Active
            </DarkBadge>
          </div>
          <div className="my-3.5" style={{ height: 1, background: 'var(--tr-12)' }} />
          <div className="flex items-center justify-between">
            <span style={{ color: 'rgba(255,255,255,0.7)', fontSize: 14 }}>Reads order receipts</span>
            <button
              type="button"
              onClick={() => {
                setModalStatus('disconnected');
                setModalOpen(true);
              }}
              style={{ color: 'var(--mint)', fontSize: 14, fontWeight: 500 }}
            >
              Manage
            </button>
          </div>
        </>
      ) : (
        <>
          <div className="flex items-center gap-3.5 mb-3.5">
            <span
              className="flex items-center justify-center shrink-0"
              style={{ width: 46, height: 46, borderRadius: 14, background: '#fff' }}
            >
              <GmailGlyph size={22} />
            </span>
            <div className="flex-1 min-w-0">
              <div className="text-white font-semibold text-[15.5px]">Connect Gmail</div>
              <div style={{ color: 'rgba(255,255,255,0.6)', fontSize: 13 }}>Auto-import from receipts</div>
            </div>
          </div>
          <p className="m-0 mb-4" style={{ color: 'rgba(255,255,255,0.7)', fontSize: 14, lineHeight: 1.45 }}>
            Let Tailor read your order emails and build your closet for you.
          </p>
          <LightButton
            fullWidth
            onClick={() => {
              setModalStatus('disconnected');
              setModalOpen(true);
            }}
          >
            Connect
          </LightButton>
        </>
      )}

      <ConnectGmailModal
        open={modalOpen}
        status={modalStatus}
        onClose={() => setModalOpen(false)}
        onConnect={handleConnect}
        onRetry={handleConnect}
        onMaybeLater={() => setModalOpen(false)}
      />
    </div>
  );
}
