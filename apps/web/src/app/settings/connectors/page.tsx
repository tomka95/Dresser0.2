'use client';

/**
 * /settings/connectors — where Tailor can find your clothes (§7 · P14).
 *
 * WIRED (real): Gmail row reflects the real connection status (GET
 * /gmail/oauth/status) and connects via the real full-page OAuth flow
 * (startGmailConnect).
 *
 * ROADMAP / HONEST: every other source (Outlook, Amazon orders, on-device
 * Photos) has no backend. Those rows are labeled "Soon" and their action is
 * disabled — we never fake a connect.
 */

import { useEffect, useState } from 'react';
import { Camera, Mail, ShoppingBag } from 'lucide-react';
import { useRequireAuth } from '@/lib/auth/useRequireAuth';
import { fetchGmailConnectionStatus, startGmailConnect } from '@/lib/api/gmail';
import { AppShell } from '@/components/layout/AppShell';
import { Btn, GmailGlyph, M, TopBar } from '@/components/ds';

export default function ConnectorsPage() {
  const { session, loading } = useRequireAuth();
  const [gmailConnected, setGmailConnected] = useState<boolean | null>(null);

  useEffect(() => {
    if (!session) return;
    let active = true;
    fetchGmailConnectionStatus()
      .then((s) => active && setGmailConnected(s.connected))
      .catch(() => active && setGmailConnected(null));
    return () => {
      active = false;
    };
  }, [session]);

  if (loading || !session) return null;

  return (
    <AppShell>
      <div style={{ padding: '62px 20px 40px' }}>
        <TopBar title="Connectors" sub="Where Tailor can find your clothes" />
        <div className="h-4" />

        <div className="flex flex-col gap-3">
          {/* Gmail — REAL. */}
          <div style={{ ...M.glass(22), padding: '15px 16px' }} className="flex items-center gap-3.5">
            <span
              className="flex shrink-0 items-center justify-center rounded-[14px]"
              style={{
                width: 42,
                height: 42,
                background: 'rgba(255,255,255,0.08)',
                border: '1px solid rgba(255,255,255,0.12)',
                color: M.soft,
              }}
            >
              <GmailGlyph size={19} />
            </span>
            <div className="min-w-0 flex-1">
              <div className="text-[14.5px] font-semibold text-white">Gmail</div>
              <div className="mt-0.5 text-[11.5px] text-white/[0.55]">
                {gmailConnected == null
                  ? 'Checking…'
                  : gmailConnected
                    ? 'Connected · receipts only'
                    : 'Import order receipts, read-only'}
              </div>
            </div>
            {gmailConnected ? (
              <span
                className="inline-flex items-center gap-1.5 rounded-full text-[10.5px] font-semibold"
                style={{
                  padding: '2.5px 9px',
                  background: 'rgba(10,207,131,0.13)',
                  border: '1px solid rgba(10,207,131,0.35)',
                  color: '#3ddf9e',
                }}
              >
                <span className="h-1.5 w-1.5 rounded-full" style={{ background: '#3ddf9e' }} /> Active
              </span>
            ) : (
              <Btn variant="glass" size="sm" onClick={() => startGmailConnect().catch(() => undefined)}>
                Connect
              </Btn>
            )}
          </div>

          {/* Roadmap sources — honest "Soon". */}
          {ROADMAP.map((c) => (
            <div
              key={c.label}
              style={{ ...M.glass(22), padding: '15px 16px', opacity: 0.6 }}
              className="flex items-center gap-3.5"
            >
              <span
                className="flex shrink-0 items-center justify-center rounded-[14px]"
                style={{
                  width: 42,
                  height: 42,
                  background: 'rgba(255,255,255,0.08)',
                  border: '1px solid rgba(255,255,255,0.12)',
                  color: M.soft,
                }}
              >
                {c.icon}
              </span>
              <div className="min-w-0 flex-1">
                <div className="text-[14.5px] font-semibold text-white">{c.label}</div>
                <div className="mt-0.5 text-[11.5px] text-white/[0.55]">{c.sub}</div>
              </div>
              <span className="text-[11.5px] text-white/[0.36]">Soon</span>
            </div>
          ))}
        </div>

        <div className="mt-4 text-[11.5px] leading-relaxed text-white/[0.36]">
          Only Gmail is live today. Other sources are on the roadmap — nothing connects until they
          ship.
        </div>
      </div>
    </AppShell>
  );
}

const ROADMAP = [
  { label: 'Outlook', sub: 'Order receipts, read-only', icon: <Mail size={19} /> },
  { label: 'Amazon orders', sub: 'Order history import', icon: <ShoppingBag size={19} /> },
  { label: 'Photos', sub: 'On-device scan for outfit shots', icon: <Camera size={19} /> },
];
