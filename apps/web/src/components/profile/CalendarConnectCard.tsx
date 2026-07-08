'use client';

/**
 * Profile card for the Google Calendar connection — mirrors GmailConnectCard.
 *   disconnected → Calendar glyph + copy + Connect (full-page OAuth redirect)
 *   connected    → Active badge + Disconnect (revokes the grant + wipes tokens)
 *
 * Connection state is REAL (GET /calendar/oauth/status). The OAuth callback
 * bounces back with ?calendar=connected|error. Connection plumbing ONLY — calendar
 * content is read live elsewhere (the Home tile + the stylist), never here.
 */

import React, { useCallback, useEffect, useState } from 'react';
import { CalendarDays } from 'lucide-react';

import { Btn, M } from '@/components/ds';
import {
  disconnectCalendar,
  fetchCalendarConnectionStatus,
  startCalendarConnect,
  type CalendarConnectionStatus,
} from '@/lib/api/calendar';

export function CalendarConnectCard() {
  const [status, setStatus] = useState<CalendarConnectionStatus | null>(null);
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    try {
      setStatus(await fetchCalendarConnectionStatus());
    } catch {
      setStatus(null);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const connected = status?.connected ?? false;

  const handleConnect = async () => {
    setBusy(true);
    try {
      await startCalendarConnect(); // full-page redirect to Google on success
    } catch {
      setBusy(false);
    }
  };

  const handleDisconnect = async () => {
    setBusy(true);
    try {
      await disconnectCalendar();
      await refresh();
    } finally {
      setBusy(false);
    }
  };

  const subline = connected
    ? 'Events read live · never stored'
    : 'Dress for what’s on your day';

  return (
    <div style={{ ...M.glass(22), padding: '15px 16px' }} className="flex items-center gap-3">
      <span
        className="flex items-center justify-center"
        style={{
          width: 42,
          height: 42,
          borderRadius: 14,
          background: 'rgba(255,255,255,0.08)',
          border: '1px solid rgba(255,255,255,0.12)',
        }}
      >
        <CalendarDays size={20} style={{ color: '#cdd6ff' }} />
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="text-[14.5px] font-semibold text-white">Calendar</span>
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
        <Btn variant="glass" size="sm" onClick={handleDisconnect} disabled={busy}>
          Disconnect
        </Btn>
      ) : (
        <Btn variant="primary" size="sm" onClick={handleConnect} disabled={busy}>
          Connect
        </Btn>
      )}
    </div>
  );
}
