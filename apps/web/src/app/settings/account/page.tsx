'use client';

/**
 * /settings/account — account deletion (P1 in the redesign).
 *
 * HONEST-DISABLED end to end: there is NO account-deletion endpoint yet, so this
 * screen is visually complete but never destroys anything. The user can type the
 * DELETE confirmation and open the danger dialog, but the final "Delete
 * everything" action stays disabled with copy that points them to support. It
 * never fakes success.
 *
 * Linked from the Settings → Account group.
 */

import { useState } from 'react';
import { Download, Trash2 } from 'lucide-react';
import { useRequireAuth } from '@/lib/auth/useRequireAuth';
import { AppShell } from '@/components/layout/AppShell';
import { Btn, DialogFrame, Field, M, TopBar } from '@/components/ds';

const CASCADE = [
  'Closet items and their photos',
  'Outfits, chats and style history',
  'Style profile and everything Tailor has learned',
  'Gmail access — revoked immediately',
];

export default function DeleteAccountPage() {
  const { session, loading } = useRequireAuth();
  const [confirmText, setConfirmText] = useState('');
  const [dialogOpen, setDialogOpen] = useState(false);

  if (loading || !session) return null;

  const typedOk = confirmText.trim().toUpperCase() === 'DELETE';

  return (
    <AppShell>
      <div style={{ padding: '62px 20px 40px' }}>
        <TopBar title="Delete account" />
        <div className="h-4" />

        {/* Export my data — the calmer escape hatch, offered before deletion.
            HONEST-DISABLED: there is no data-export endpoint yet, so this points
            to support instead of faking a download. */}
        <div style={{ ...M.glass(24), padding: '16px 18px' }}>
          <div className="flex items-start gap-3.5">
            <span
              className="flex shrink-0 items-center justify-center rounded-xl"
              style={{
                width: 36,
                height: 36,
                background: 'rgba(255,255,255,0.08)',
                border: '1px solid rgba(255,255,255,0.09)',
                color: M.soft,
              }}
            >
              <Download size={16} />
            </span>
            <div className="min-w-0 flex-1">
              <div className="text-[14.5px] font-medium text-white">Export my data</div>
              <div className="mt-1 text-[12.5px] leading-relaxed text-white/[0.55]">
                Prefer a pause over deleting? Take your closet, outfits and style profile with you.
              </div>
            </div>
          </div>
          <Btn
            variant="glass"
            fullWidth
            size="md"
            className="mt-3.5"
            disabled
            title="Data export isn't available yet"
          >
            Export coming soon
          </Btn>
          <div className="mt-2 text-[11.5px] leading-snug text-white/[0.36]">
            Self-serve export isn&rsquo;t wired yet. To request a copy today, email{' '}
            <a href="mailto:support@tailor.app" className="text-white/[0.55] underline">
              support@tailor.app
            </a>
            .
          </div>
        </div>

        <div className="h-3.5" />

        <div
          style={{
            ...M.glass(24),
            boxShadow: 'none',
            padding: '18px 20px',
            background: 'rgba(251,44,54,0.06)',
            border: '1px solid rgba(251,44,54,0.22)',
          }}
        >
          <div className="text-[16px] font-semibold text-white" style={{ letterSpacing: '-0.3px' }}>
            This is permanent
          </div>
          <div className="mt-1 text-[13px] leading-relaxed text-white/[0.55]">
            Deleting your account would remove, everywhere:
          </div>
          <div className="mt-3">
            {CASCADE.map((t, i) => (
              <div
                key={t}
                className="flex items-center gap-2.5"
                style={{
                  padding: '10.5px 0',
                  borderBottom: i < CASCADE.length - 1 ? '1px solid rgba(255,255,255,0.06)' : 'none',
                }}
              >
                <Trash2 size={14} style={{ color: '#ff8087', flexShrink: 0 }} />
                <span className="text-[13px] text-white/[0.78]">{t}</span>
              </div>
            ))}
          </div>
        </div>

        {/* Honest banner: deletion is not available yet. */}
        <div
          className="mt-3.5 rounded-2xl"
          style={{
            padding: '13px 15px',
            background: 'rgba(240,162,59,0.12)',
            border: '1px solid rgba(240,162,59,0.32)',
          }}
        >
          <div className="text-[13px] leading-relaxed" style={{ color: '#fff' }}>
            Account deletion isn&rsquo;t available in the app yet. To delete your account today,
            contact support at{' '}
            <a href="mailto:support@tailor.app" className="font-semibold" style={{ color: '#f0b566' }}>
              support@tailor.app
            </a>
            .
          </div>
        </div>

        <div className="mt-4 text-[12px] leading-relaxed text-white/[0.55]">
          When it ships, deletion will purge backups within 30 days. Type{' '}
          <b className="text-white">DELETE</b> to confirm:
        </div>
        <div className="mt-2.5">
          <Field value={confirmText} onChange={setConfirmText} placeholder="DELETE" />
        </div>

        <div className="mt-4 flex flex-col" style={{ gap: 9 }}>
          {/* Opens the danger dialog only once DELETE is typed. The dialog's final
              action is disabled — deletion has no endpoint. */}
          <Btn variant="danger" fullWidth size="md" disabled={!typedOk} onClick={() => setDialogOpen(true)}>
            Delete everything
          </Btn>
          <Btn variant="ghost" fullWidth size="md" onClick={() => history.back()}>
            Keep my account
          </Btn>
        </div>
      </div>

      {/* Final danger confirm — HONEST-DISABLED action. */}
      <DialogFrame
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        iconTone="danger"
        icon={<Trash2 size={23} />}
        title="Not available yet"
        sub="Account deletion isn't wired up in the app. Contact support@tailor.app and we'll delete your account for you."
      >
        <div className="mt-5 flex flex-col" style={{ gap: 9 }}>
          <Btn variant="danger" fullWidth size="md" disabled title="No deletion endpoint yet">
            Delete everything
          </Btn>
          <Btn variant="ghost" fullWidth size="md" onClick={() => setDialogOpen(false)}>
            Close
          </Btn>
        </div>
      </DialogFrame>
    </AppShell>
  );
}
