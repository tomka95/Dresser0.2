'use client';

/**
 * A10 · Expired session — a mid-session re-auth interstitial.
 *
 * Shown when a still-open app session's token has lapsed (e.g. a 401 comes back
 * from an authed fetch while the user was away). The messaging is deliberately
 * calm and context-preserving: the user is told nothing was lost and that they
 * will return to exactly what they were doing after signing back in.
 *
 * This is a presentational, reusable screen. It renders on the §0 DialogFrame
 * surface (deep-glass medallion → title → copy → action stack) and is used both
 * by the /session-expired route and anywhere the app wants to interrupt with a
 * re-auth prompt.
 *
 * TRIGGER (where this would fire from): useRequireAuth (src/lib/auth/
 * useRequireAuth.ts) resolves the session and redirects to `redirectTo` when it
 * becomes null. For a MID-SESSION lapse — a 401 on an authed request after the
 * page already rendered as authenticated — the guard/API layer would route here
 * with the current location captured as `?next=`, so that after re-auth the user
 * lands back where they were. This screen owns the UI only; it does NOT rewire
 * the guard. See the route at app/(auth)/session-expired/page.tsx.
 */

import React from 'react';
import { useRouter } from 'next/navigation';
import { Lock } from 'lucide-react';
import { Btn, DialogFrame, M } from '@/components/ds';
import { GoogleIcon } from '@/components/icons/GoogleIcon';
import { signInWithProvider } from '@/lib/auth';
import type { AuthProviderId } from '@/config/authProviders';

interface SessionExpiredScreenProps {
  /**
   * Where to return the user after they sign back in. Preserved through the
   * sign-in route so re-auth lands them exactly where they left off.
   */
  next?: string;
  /**
   * Optional one-line note about the preserved context (e.g. "Draft message
   * saved"). Rendered as a quiet footnote under the actions when provided.
   */
  contextNote?: string;
}

export function SessionExpiredScreen({ next, contextNote }: SessionExpiredScreenProps) {
  const router = useRouter();

  // Carry the return path into the email sign-in route so it can bounce back.
  const emailHref = next
    ? `/sign-in?next=${encodeURIComponent(next)}`
    : '/sign-in';

  const handleProvider = async (id: AuthProviderId) => {
    try {
      // Full-page redirect to the provider and back through /auth/callback.
      await signInWithProvider(id);
    } catch {
      // Fall back to the email route if the provider redirect can't start.
      router.push(emailHref);
    }
  };

  return (
    <DialogFrame
      open
      icon={<Lock size={24} />}
      iconTone="plain"
      title="Your session expired"
      sub="Your session timed out while you were away. Sign back in and you'll land exactly where you left off — nothing was lost."
    >
      <div className="mt-[18px] flex flex-col gap-2">
        <Btn
          variant="primary"
          fullWidth
          size="md"
          icon={<GoogleIcon className="h-[17px] w-[17px]" />}
          onClick={() => handleProvider('google')}
        >
          Continue with Google
        </Btn>
        <Btn variant="glass" fullWidth size="md" onClick={() => router.push(emailHref)}>
          Use email instead
        </Btn>
      </div>
      {contextNote && (
        <div className="mt-[14px]" style={{ color: M.ghost, fontSize: 11.5 }}>
          {contextNote}
        </div>
      )}
    </DialogFrame>
  );
}
