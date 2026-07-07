'use client';

/**
 * A10 · Expired session route.
 *
 * A thin wrapper that renders the reusable <SessionExpiredScreen/>. It reads the
 * return path (?next=) and an optional context note (?note=) from the URL on
 * mount — via window.location rather than useSearchParams, so the page needs no
 * Suspense boundary (matching the sign-in page's approach).
 *
 * WHERE THIS IS TRIGGERED FROM: this is the landing target for a mid-session
 * re-auth. The app's auth guard / API layer (useRequireAuth in
 * src/lib/auth/useRequireAuth.ts, which today redirects to /sign-in when the
 * session resolves to null) would send an already-loaded, now-401 session here
 * with `?next=<current path>` so re-auth returns the user to where they were.
 * That rewiring is intentionally NOT done here — this route only supplies the UI.
 */

import { useEffect, useState } from 'react';
import { SessionExpiredScreen } from '@/components/auth/SessionExpiredScreen';

export default function SessionExpiredPage() {
  const [next, setNext] = useState<string | undefined>(undefined);
  const [note, setNote] = useState<string | undefined>(undefined);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const n = params.get('next');
    const m = params.get('note');
    if (n) setNext(n);
    if (m) setNote(m);
  }, []);

  return <SessionExpiredScreen next={next} contextNote={note} />;
}
