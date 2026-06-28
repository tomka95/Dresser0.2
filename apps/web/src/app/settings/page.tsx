'use client';

import React, { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import {
  Bell,
  ChevronRight,
  KeyRound,
  Mail,
  Ruler,
  RefreshCw,
  Scale,
  Sparkles,
} from 'lucide-react';

import { useRequireAuth } from '@/lib/auth/useRequireAuth';
import { signOut } from '@/lib/auth';
import { getCurrentUser } from '@/lib/api/auth';
import { fetchGmailConnectionStatus } from '@/lib/api/gmail';
import { AppShell } from '@/components/layout/AppShell';
import { TopBar } from '@/components/ui/TopBar';
import { GlassCard } from '@/components/ui/GlassCard';
import { Avatar } from '@/components/ui/Avatar';
import { Switch } from '@/components/ui/Switch';

function GroupLabel({ children }: { children: React.ReactNode }) {
  return (
    <div
      className="mb-2 mt-1 px-1 font-accent text-[12px] font-semibold uppercase"
      style={{ color: 'rgba(255,255,255,0.5)', letterSpacing: '0.6px' }}
    >
      {children}
    </div>
  );
}

function Row({
  icon,
  label,
  value,
  control,
  onClick,
  isLast,
}: {
  icon?: React.ReactNode;
  label: React.ReactNode;
  value?: string;
  control?: React.ReactNode;
  onClick?: () => void;
  isLast?: boolean;
}) {
  const Tag = onClick ? 'button' : 'div';
  return (
    <Tag
      type={onClick ? 'button' : undefined}
      onClick={onClick}
      className="flex w-full items-center gap-3 px-2 py-2.5 text-left"
      style={{
        borderBottom: isLast ? 'none' : '1px solid rgba(255,255,255,0.08)',
      }}
    >
      {icon && (
        <span
          className="flex items-center justify-center"
          style={{
            width: 36,
            height: 36,
            borderRadius: 12,
            background: 'var(--tr-10)',
            color: 'rgba(255,255,255,0.9)',
            flexShrink: 0,
          }}
        >
          {icon}
        </span>
      )}
      <span className="min-w-0 flex-1 text-[15px] text-white">{label}</span>
      {value && (
        <span className="text-[13px]" style={{ color: 'rgba(255,255,255,0.5)' }}>
          {value}
        </span>
      )}
      {control}
    </Tag>
  );
}

const Chevron = () => <ChevronRight size={18} color="rgba(255,255,255,0.4)" />;

export default function SettingsPage() {
  const router = useRouter();
  const { status } = useRequireAuth();
  const isAuth = status === 'authenticated';

  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [avatarUrl, setAvatarUrl] = useState<string | null>(null);
  const [gmailConnected, setGmailConnected] = useState<boolean | null>(null);

  // Local-only toggle — TODO: not backed by API
  const [notifications, setNotifications] = useState(true);
  const [loggingOut, setLoggingOut] = useState(false);

  useEffect(() => {
    if (!isAuth) return;
    let active = true;

    getCurrentUser()
      .then((u) => {
        if (!active) return;
        setName(u.display_name || u.full_name || u.email || '');
        setEmail(u.email || '');
        setAvatarUrl(u.avatar_url ?? null);
      })
      .catch(() => {});

    fetchGmailConnectionStatus()
      .then((s) => {
        if (!active) return;
        setGmailConnected(s.connected);
      })
      .catch(() => {
        if (active) setGmailConnected(false);
      });

    return () => {
      active = false;
    };
  }, [isAuth]);

  async function handleLogout() {
    setLoggingOut(true);
    try {
      await signOut();
      router.push('/sign-in');
    } catch {
      setLoggingOut(false);
    }
  }

  if (status === 'loading' || !isAuth) {
    return (
      <AppShell contentClassName="px-5 pt-12">
        <div className="h-10 w-10 rounded-full bg-white/5 animate-pulse" />
      </AppShell>
    );
  }

  return (
    <AppShell contentClassName="px-5 pt-12 pb-12">
      <TopBar title="Settings" />

      <div className="mt-6 space-y-7">
        {/* Account */}
        <section>
          <GroupLabel>Account</GroupLabel>
          <GlassCard tint="scrim" padding={6}>
            <Row
              icon={<Avatar name={name || 'You'} size={28} src={avatarUrl} />}
              label={
                <span className="flex min-w-0 flex-col">
                  <span className="truncate text-[15px] text-white">{name || 'You'}</span>
                  <span className="truncate text-[12.5px]" style={{ color: 'rgba(255,255,255,0.5)' }}>
                    {email}
                  </span>
                </span>
              }
            />
            <Row
              icon={<KeyRound size={18} />}
              label="Password"
              control={<Chevron />}
              onClick={() => router.push('/reset-password')}
            />
            {/* TODO: not backed by API */}
            <Row
              icon={<Ruler size={18} />}
              label="Sizes & fit"
              control={<Chevron />}
              onClick={() => {}}
              isLast
            />
          </GlassCard>
        </section>

        {/* Connected accounts */}
        <section>
          <GroupLabel>Connected accounts</GroupLabel>
          <GlassCard tint="scrim" padding={6}>
            <Row
              icon={<Mail size={18} />}
              label="Gmail"
              value={
                gmailConnected == null
                  ? '…'
                  : gmailConnected
                    ? 'Connected'
                    : 'Not connected'
              }
              // TODO: not backed by API — toggling is a non-functional placeholder
              control={
                <Switch
                  checked={!!gmailConnected}
                  onCheckedChange={() => {}}
                  aria-label="Gmail connection"
                />
              }
            />
            {/* TODO: not backed by API */}
            <Row
              icon={<RefreshCw size={18} />}
              label="Sync frequency"
              value="Daily"
              control={<Chevron />}
              onClick={() => {}}
              isLast
            />
          </GlassCard>
        </section>

        {/* Preferences */}
        <section>
          <GroupLabel>Preferences</GroupLabel>
          <GlassCard tint="scrim" padding={6}>
            {/* TODO: not backed by API */}
            <Row
              icon={<Sparkles size={18} />}
              label="Style preferences"
              control={<Chevron />}
              onClick={() => {}}
            />
            {/* TODO: not backed by API — local only */}
            <Row
              icon={<Bell size={18} />}
              label="Notifications"
              control={
                <Switch
                  checked={notifications}
                  onCheckedChange={setNotifications}
                  aria-label="Notifications"
                />
              }
            />
            {/* TODO: not backed by API */}
            <Row
              icon={<Scale size={18} />}
              label="Units"
              value="Metric"
              control={<Chevron />}
              onClick={() => {}}
              isLast
            />
          </GlassCard>
        </section>

        {/* Log out */}
        <button
          type="button"
          onClick={handleLogout}
          disabled={loggingOut}
          className="w-full rounded-full text-[15px] font-semibold transition-transform active:scale-[0.98] disabled:opacity-60"
          style={{
            height: 50,
            border: '1px solid rgba(251,44,54,0.4)',
            background: 'rgba(251,44,54,0.12)',
            color: '#ff6b6b',
          }}
        >
          {loggingOut ? 'Logging out…' : 'Log out'}
        </button>

        <p className="text-center text-[12.5px]" style={{ color: 'rgba(255,255,255,0.35)' }}>
          Tailor v2.0.0
        </p>
      </div>
    </AppShell>
  );
}
