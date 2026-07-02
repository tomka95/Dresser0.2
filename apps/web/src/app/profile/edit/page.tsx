'use client';

/**
 * /profile/edit — edit profile. REAL: full name saves to Supabase user metadata
 * (the source /auth/me mirrors). LOCAL-ONLY: username & bio (no backend fields
 * yet — persisted to localStorage), avatar change (no upload endpoint).
 */

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { Pencil } from 'lucide-react';
import { useRequireAuth } from '@/lib/auth/useRequireAuth';
import { getCurrentUser } from '@/lib/api/auth';
import { updateProfileName } from '@/lib/auth';
import { AppShell } from '@/components/layout/AppShell';
import { DSAvatar, DSButton, FormField, TopBar } from '@/components/ds';

const STORAGE_KEY = 'tailor.pref.profileExtras';

export default function EditProfilePage() {
  const router = useRouter();
  const { session, loading } = useRequireAuth();
  const isAuth = !!session;

  const [fullName, setFullName] = useState('');
  const [username, setUsername] = useState('');
  const [email, setEmail] = useState('');
  const [bio, setBio] = useState('');
  const [avatarUrl, setAvatarUrl] = useState<string | undefined>(undefined);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  useEffect(() => {
    if (!isAuth) return;
    let active = true;
    getCurrentUser()
      .then((u) => {
        if (!active) return;
        setFullName(u.display_name || u.full_name || '');
        setEmail(u.email);
        setAvatarUrl(u.avatar_url ?? undefined);
      })
      .catch(() => {
        if (active && session?.user) {
          const meta = (session.user.user_metadata ?? {}) as { full_name?: string; avatar_url?: string };
          setFullName(meta.full_name ?? '');
          setEmail(session.user.email ?? '');
          setAvatarUrl(meta.avatar_url);
        }
      });
    try {
      const raw = window.localStorage.getItem(STORAGE_KEY);
      if (raw) {
        const extras = JSON.parse(raw) as { username?: string; bio?: string };
        if (extras.username) setUsername(extras.username);
        if (extras.bio) setBio(extras.bio);
      }
    } catch {
      /* keep defaults */
    }
    return () => {
      active = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isAuth]);

  if (loading || !isAuth) return null;

  const handleSave = async () => {
    setBusy(true);
    setNote(null);
    try {
      if (fullName.trim()) {
        await updateProfileName(fullName.trim());
      }
      try {
        window.localStorage.setItem(STORAGE_KEY, JSON.stringify({ username, bio }));
      } catch {
        /* in-memory only */
      }
      setNote('Saved ✓');
      setTimeout(() => router.push('/profile'), 700);
    } catch (err) {
      setNote(err instanceof Error ? err.message : "Couldn't save changes.");
      setBusy(false);
    }
  };

  return (
    <AppShell>
      <div className="flex min-h-full flex-col" style={{ padding: '48px 24px 40px' }}>
        <TopBar
          title="Edit profile"
          right={
            <button
              type="button"
              onClick={handleSave}
              disabled={busy}
              className="text-[15px] font-semibold disabled:opacity-50"
              style={{ color: 'var(--mint)' }}
            >
              Save
            </button>
          }
        />

        <div className="my-3.5 mb-[26px] flex flex-col items-center">
          <div className="relative">
            <DSAvatar name={fullName || email} src={avatarUrl} size={92} ring />
            <button
              type="button"
              aria-label="Change photo"
              onClick={() => setNote('Photo upload is coming soon.')}
              className="absolute flex items-center justify-center rounded-full"
              style={{
                right: -2,
                bottom: -2,
                width: 32,
                height: 32,
                background: 'var(--mint)',
                color: 'var(--brand-teal)',
                border: '3px solid #1e1e1e',
              }}
            >
              <Pencil size={15} />
            </button>
          </div>
          <div className="mt-3 text-[13px] text-white/60">Change photo</div>
        </div>

        <div className="flex flex-col gap-4">
          <FormField label="Full name" value={fullName} onChange={setFullName} placeholder="Your name" />
          <FormField label="Username" value={username} onChange={setUsername} placeholder="@you" />
          <FormField label="Email" value={email} disabled />
          <FormField label="Bio" value={bio} onChange={setBio} placeholder="A line about your style" multiline />
        </div>

        {note && (
          <p className="mt-4 text-center text-[13px]" style={{ color: 'rgba(255,255,255,0.7)' }}>
            {note}
          </p>
        )}

        <div className="flex-1" />
        <DSButton variant="light" fullWidth pill className="mt-6" loading={busy} disabled={busy} onClick={handleSave}>
          {busy ? 'Saving…' : 'Save changes'}
        </DSButton>
      </div>
    </AppShell>
  );
}
