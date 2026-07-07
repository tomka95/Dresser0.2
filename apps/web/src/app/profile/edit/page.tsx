'use client';

/**
 * /profile/edit — edit profile.
 *
 * WIRED (real): full name → Supabase user metadata via updateProfileName
 * (the source /auth/me mirrors).
 *
 * DEVICE-ONLY (labeled): username & bio have no backend field yet, so they
 * persist to localStorage on this device only.
 *
 * HONEST-DISABLED: avatar "Change photo" — there is no upload endpoint, so the
 * control is disabled with a "coming soon" title. It never reports fake success.
 *
 * Email is read-only (changing the sign-in email is not wired here).
 */

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { Camera } from 'lucide-react';
import { useRequireAuth } from '@/lib/auth/useRequireAuth';
import { getCurrentUser } from '@/lib/api/auth';
import { updateProfileName } from '@/lib/auth';
import { AppShell } from '@/components/layout/AppShell';
import { Btn, DSAvatar, Field, TopBar, useToastStore } from '@/components/ds';

const STORAGE_KEY = 'tailor.pref.profileExtras';

export default function EditProfilePage() {
  const router = useRouter();
  const { session, loading } = useRequireAuth();
  const isAuth = !!session;
  const toast = useToastStore((s) => s.toast);

  const [fullName, setFullName] = useState('');
  const [username, setUsername] = useState('');
  const [email, setEmail] = useState('');
  const [bio, setBio] = useState('');
  const [avatarUrl, setAvatarUrl] = useState<string | undefined>(undefined);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

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
    setError(null);
    try {
      if (fullName.trim()) {
        await updateProfileName(fullName.trim());
      }
      try {
        window.localStorage.setItem(STORAGE_KEY, JSON.stringify({ username, bio }));
      } catch {
        /* in-memory only */
      }
      toast({ tone: 'success', title: 'Profile saved' });
      setTimeout(() => router.push('/profile'), 500);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't save changes.");
      setBusy(false);
    }
  };

  return (
    <AppShell>
      <div style={{ padding: '62px 20px 40px' }}>
        <TopBar
          title="Edit profile"
          right={
            <Btn size="sm" pending={busy} onClick={handleSave}>
              Save
            </Btn>
          }
        />

        {/* Avatar — HONEST-DISABLED: no upload endpoint, so the camera control is
            disabled with a "coming soon" title. Never fakes success. */}
        <div className="flex justify-center" style={{ margin: '18px 0 22px' }}>
          <div className="relative">
            <DSAvatar name={fullName || email} src={avatarUrl} size={92} ring />
            <button
              type="button"
              aria-label="Change photo"
              title="Photo upload coming soon"
              disabled
              className="absolute flex cursor-not-allowed items-center justify-center rounded-full opacity-60"
              style={{
                right: -2,
                bottom: -2,
                width: 32,
                height: 32,
                background: 'var(--mint)',
                color: 'var(--brand-teal)',
                border: '2px solid #101b1a',
              }}
            >
              <Camera size={15} />
            </button>
          </div>
        </div>
        <div className="mb-5 text-center text-[11.5px] text-white/[0.36]">Photo upload coming soon</div>

        <div className="flex flex-col" style={{ gap: 14 }}>
          <Field label="Name" value={fullName} onChange={setFullName} placeholder="Your name" />
          <Field label="Username" value={username} onChange={setUsername} placeholder="@you" />
          <Field
            label="Bio"
            value={bio}
            onChange={setBio}
            placeholder="A line about your style"
            multiline
          />
          <Field
            label="Email"
            value={email}
            disabled
            right={<span className="text-[11.5px] text-white/[0.36]">verified</span>}
          />
        </div>

        <div className="mt-3.5 text-[11.5px] leading-snug text-white/[0.36]">
          Username and bio are saved on this device only — Tailor doesn&rsquo;t have a profile
          field for them yet.
        </div>

        {error && (
          <p className="mt-4 text-center text-[13px]" style={{ color: '#ff8087' }}>
            {error}
          </p>
        )}

        <Btn variant="primary" fullWidth size="lg" className="mt-6" pending={busy} onClick={handleSave}>
          Save changes
        </Btn>
      </div>
    </AppShell>
  );
}
