'use client';

/**
 * useGenerationRunStatus — the shared Wave 2 status poll.
 *
 * Polls GET /gmail/ingest/status?sync_id= every 1.5s and reports { ready, total, done }.
 * `done` flips when the run leaves 'running' OR every target has settled
 * (ready + failed >= total), then polling stops. Both the post-commit
 * GenerationProgressPill and the global BackgroundTailorNotice use this so there is ONE
 * poll implementation.
 */
import { useEffect, useRef, useState } from 'react';

import { getIngestStatus } from '@/lib/api/gmail';

export function useGenerationRunStatus(syncId: string, initialTotal = 0) {
  const [ready, setReady] = useState(0);
  const [total, setTotal] = useState(initialTotal);
  const [done, setDone] = useState(false);

  const mountedRef = useRef(true);
  const timersRef = useRef<ReturnType<typeof setTimeout>[]>([]);

  useEffect(() => {
    mountedRef.current = true;
    setDone(false);
    async function poll() {
      if (!mountedRef.current) return;
      try {
        const st = await getIngestStatus(syncId);
        if (!mountedRef.current) return;
        const gt = st.progress.generation_total || 0;
        const gr = st.progress.generation_ready || 0;
        const gf = st.progress.generation_failed || 0;
        setReady(gr);
        if (gt > 0) setTotal(gt);
        if (st.status !== 'running' || (gt > 0 && gr + gf >= gt)) {
          setDone(true);
          return; // stop polling
        }
      } catch {
        /* transient — keep polling */
      }
      timersRef.current.push(setTimeout(poll, 1500));
    }
    poll();
    return () => {
      mountedRef.current = false;
      timersRef.current.forEach(clearTimeout);
      timersRef.current = [];
    };
  }, [syncId]);

  return { ready, total, done };
}
