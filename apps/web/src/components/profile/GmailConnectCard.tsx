'use client';

import React, { useCallback, useEffect, useState } from 'react';
import { Check, Mail } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { ConnectGmailModal } from '@/components/auth/ConnectGmailModal';
import {
  fetchGmailConnectionStatus,
  startGmailConnect,
  type GmailConnectionStatus,
} from '@/lib/api/gmail';

/**
 * Profile card for the Gmail connection.
 *
 * Reflects the real connected state read from the backend (google_accounts) and
 * lets the user start the connect flow via ConnectGmailModal. This is connection
 * plumbing ONLY — it never triggers ingestion.
 */
export function GmailConnectCard() {
  const [status, setStatus] = useState<GmailConnectionStatus | null>(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);

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
    if (params.get('gmail') === 'error') {
      setError('Gmail connection failed. Please try again.');
    }
  }, [refresh]);

  const handleConnect = async () => {
    setError(null);
    try {
      await startGmailConnect(); // full-page redirect to Google on success
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Could not start Gmail connection.');
      setModalOpen(false);
    }
  };

  const connected = status?.connected ?? false;

  return (
    <div className="mx-4 my-3 rounded-2xl bg-white/5 border border-white/10 p-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Mail className="h-5 w-5 text-white/80" />
          <div>
            <p className="text-white font-medium">Gmail</p>
            <p className="text-sm text-white/50">
              {connected
                ? 'Connected — receipts can be imported'
                : 'Connect to import purchases from receipts'}
            </p>
          </div>
        </div>

        {connected ? (
          <span className="inline-flex items-center gap-1 text-sm text-green-400">
            <Check className="h-4 w-4" /> Connected
          </span>
        ) : (
          <Button
            type="button"
            onClick={() => setModalOpen(true)}
            className="h-9 rounded-full px-4 bg-white text-black hover:bg-white/90"
          >
            Connect
          </Button>
        )}
      </div>

      {error && <p className="mt-2 text-sm text-red-400">{error}</p>}

      <ConnectGmailModal
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        onConnect={handleConnect}
        onMaybeLater={() => setModalOpen(false)}
      />
    </div>
  );
}
