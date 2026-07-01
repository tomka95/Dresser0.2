'use client';

/**
 * /gmail-sync is retired. The Gmail → closet flow now lives at /review, where a
 * sync starts ONLY from the explicit "Scan my inbox" CTA (no auto-extraction on
 * mount, and no calls to the removed /gmail/clothing-items endpoint).
 *
 * This stub exists solely to redirect any lingering links/bookmarks to the single
 * ingest entry point so there is exactly one place a sync can begin.
 */

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';

export default function GmailSyncRedirect() {
  const router = useRouter();
  useEffect(() => {
    router.replace('/review');
  }, [router]);
  return null;
}
