'use client';

/**
 * /settings/account — account deletion + data export (App Store 5.1.1 / GDPR).
 *
 * REAL end to end now: the export button downloads a JSON of the user's data, and
 * the delete flow (type-to-confirm → danger dialog → DELETE /account) irreversibly
 * erases the account server-side, then signs the user out to the landing screen.
 *
 * Linked from the Settings → Account group.
 */

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { Download, Trash2 } from 'lucide-react';
import { useRequireAuth } from '@/lib/auth/useRequireAuth';
import { signOut } from '@/lib/auth';
import { deleteAccount, exportAccountData } from '@/lib/api/account';
import { AppShell } from '@/components/layout/AppShell';
import { Btn, DialogFrame, Field, M, TopBar } from '@/components/ds';

const CASCADE = [
  'Closet items and their photos',
  'Outfits, chats and style history',
  'Style profile and everything Tailor has learned',
  'Gmail and Calendar access — revoked immediately',
];

export default function DeleteAccountPage() {
  const router = useRouter();
  const { session, loading } = useRequireAuth();
  const [confirmText, setConfirmText] = useState('');
  const [dialogOpen, setDialogOpen] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (loading || !session) return null;

  const typedOk = confirmText.trim().toUpperCase() === 'DELETE';

  const handleExport = async () => {
    setError(null);
    setExporting(true);
    try {
      await exportAccountData();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not export your data.');
    } finally {
      setExporting(false);
    }
  };

  const handleDelete = async () => {
    setError(null);
    setDeleting(true);
    try {
      await deleteAccount(confirmText.trim().toUpperCase());
      // Erasure succeeded: drop the (now-orphaned) local session and land on sign-in.
      await signOut().catch(() => {});
      router.replace('/sign-in');
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not delete your account.');
      setDeleting(false);
      setDialogOpen(false);
    }
  };

  return (
    <AppShell>
      <div style={{ padding: '62px 20px 40px' }}>
        <TopBar title="Delete account" />
        <div className="h-4" />

        {/* Export my data — the calmer escape hatch, offered before deletion. */}
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
            pending={exporting}
            onClick={handleExport}
          >
            {exporting ? 'Preparing…' : 'Download my data'}
          </Btn>
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
            Deleting your account removes, everywhere:
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

        <div className="mt-4 text-[12px] leading-relaxed text-white/[0.55]">
          This can&rsquo;t be undone. Type <b className="text-white">DELETE</b> to confirm:
        </div>
        <div className="mt-2.5">
          <Field value={confirmText} onChange={setConfirmText} placeholder="DELETE" />
        </div>

        {error && (
          <div
            className="mt-3 rounded-xl text-[12.5px] leading-relaxed"
            style={{
              padding: '10px 13px',
              background: 'rgba(251,44,54,0.10)',
              border: '1px solid rgba(251,44,54,0.28)',
              color: '#ff8087',
            }}
          >
            {error}
          </div>
        )}

        <div className="mt-4 flex flex-col" style={{ gap: 9 }}>
          <Btn variant="danger" fullWidth size="md" disabled={!typedOk} onClick={() => setDialogOpen(true)}>
            Delete everything
          </Btn>
          <Btn variant="ghost" fullWidth size="md" onClick={() => history.back()}>
            Keep my account
          </Btn>
        </div>
      </div>

      {/* Final danger confirm — REAL deletion. */}
      <DialogFrame
        open={dialogOpen}
        onOpenChange={(o) => {
          if (!deleting) setDialogOpen(o);
        }}
        iconTone="danger"
        icon={<Trash2 size={23} />}
        title="Delete your account?"
        sub="This permanently erases your closet, outfits, chats and style profile, and revokes Gmail and Calendar access. It can't be undone."
      >
        <div className="mt-5 flex flex-col" style={{ gap: 9 }}>
          <Btn variant="danger" fullWidth size="md" pending={deleting} onClick={handleDelete}>
            {deleting ? 'Deleting…' : 'Delete everything'}
          </Btn>
          <Btn variant="ghost" fullWidth size="md" disabled={deleting} onClick={() => setDialogOpen(false)}>
            Cancel
          </Btn>
        </div>
      </DialogFrame>
    </AppShell>
  );
}
