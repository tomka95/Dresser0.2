'use client';

/**
 * /scan — Tag / barcode scan (§3 · C6, ROADMAP).
 *
 * The redesign shows a 4th ingest source: point the camera at a care label or
 * barcode and let brand / size / fabric fill in automatically. There is NO scan
 * backend yet, so this screen is deliberately HONEST:
 *   - the viewfinder + animated scan line are the roadmap visual,
 *   - the capture / "look up" action is DISABLED with a "Coming soon" label —
 *     it never pretends to read a tag,
 *   - camera permission is surfaced with the real Permissions API + the shared
 *     PermissionState block; we never fake a granted camera.
 *
 * Reachable from the closet FAB row ("Scan a tag" link). Roadmap-visual, not wired.
 */

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { Image as ImageIcon } from 'lucide-react';
import { AppShell } from '@/components/layout/AppShell';
import { useRequireAuth } from '@/lib/auth/useRequireAuth';
import { Btn, RoundBtn, TopBar, Thinking, PermissionState, M } from '@/components/ds';

type CamState = 'unknown' | 'prompt' | 'granted' | 'denied' | 'unavailable';

export default function ScanPage() {
  const router = useRouter();
  // App closet-ingest feature — gate like /add-photo (renders nothing until authed).
  const { session, loading } = useRequireAuth();
  const [cam, setCam] = useState<CamState>('unknown');

  // Read the real camera permission via the Permissions API (where supported).
  // We only READ state here — no getUserMedia, nothing is captured — because the
  // scan backend doesn't exist yet. This keeps the roadmap screen honest about
  // what the OS would ask for without pretending the feature works.
  useEffect(() => {
    let cancelled = false;
    const perms = typeof navigator !== 'undefined' ? navigator.permissions : undefined;
    if (!perms || typeof perms.query !== 'function') {
      setCam('unavailable');
      return;
    }
    perms
      // `camera` isn't in every lib.dom PermissionName union yet.
      .query({ name: 'camera' as PermissionName })
      .then((status) => {
        if (cancelled) return;
        const apply = () => setCam(status.state as CamState);
        apply();
        status.onchange = apply;
      })
      .catch(() => {
        if (!cancelled) setCam('unavailable');
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (loading || !session) return <AppShell scroll={false}><div /></AppShell>;

  // Camera off / unavailable → the shared amber permission block (honest copy:
  // Tailor would use the camera, nothing is captured yet).
  if (cam === 'denied' || cam === 'unavailable') {
    return (
      <AppShell>
        <div style={{ padding: '4px 20px' }}>
          <TopBar title="Scan a tag" onBack={() => router.back()} />
          <div style={{ marginTop: 40 }}>
            <PermissionState kind="camera" />
          </div>
        </div>
      </AppShell>
    );
  }

  return (
    <AppShell scroll={false}>
      <div className="relative h-full">
        <TopBar
          title="Scan a tag"
          onBack={() => router.back()}
          right={
            <RoundBtn
              size={40}
              style={{ borderRadius: 14 }}
              aria-label="Pick from photos instead"
              onClick={() => router.push('/add-photo')}
              icon={<ImageIcon size={17} />}
            />
          }
        />

        {/* Viewfinder — cut-out frame with mint corner brackets + a sweeping scan
            line. Pure roadmap visual; no live camera stream is attached. */}
        <div
          className="absolute"
          style={{
            top: 120,
            left: 34,
            right: 34,
            bottom: 220,
            borderRadius: 30,
            border: '1.5px solid rgba(255,255,255,0.35)',
            boxShadow: '0 0 0 2000px rgba(0,0,0,0.5)',
          }}
          aria-hidden
        >
          {(
            [
              ['top', 'left'],
              ['top', 'right'],
              ['bottom', 'left'],
              ['bottom', 'right'],
            ] as const
          ).map(([v, hz]) => (
            <span
              key={`${v}-${hz}`}
              style={{
                position: 'absolute',
                [v]: -2,
                [hz]: -2,
                width: 30,
                height: 30,
                borderRadius: 6,
                [`border${v[0].toUpperCase()}${v.slice(1)}` as 'borderTop' | 'borderBottom']:
                  '3px solid var(--mint)',
                [`border${hz[0].toUpperCase()}${hz.slice(1)}` as 'borderLeft' | 'borderRight']:
                  '3px solid var(--mint)',
              }}
            />
          ))}
          <span
            style={{
              position: 'absolute',
              left: 14,
              right: 14,
              height: 2,
              borderRadius: 1,
              background: 'linear-gradient(90deg, transparent, var(--mint), transparent)',
              boxShadow: '0 0 16px rgba(75,226,214,0.8)',
              animation: 't2-scan 2.8s cubic-bezier(0.65,0,0.35,1) infinite',
            }}
          />
          <div
            style={{
              position: 'absolute',
              left: 0,
              right: 0,
              bottom: -54,
              textAlign: 'center',
              color: M.soft,
              fontSize: 13.5,
            }}
          >
            Frame the care tag or barcode
          </div>
        </div>

        {/* Honest status + disabled capture. The scan backend isn't built, so the
            action is visibly "Coming soon" and never fires a lookup. */}
        <div className="absolute" style={{ left: 20, right: 20, bottom: 34 }}>
          <div
            className="flex items-center"
            style={{ ...M.deep(22), padding: '14px 16px', gap: 12, marginBottom: 12 }}
          >
            <Thinking size={30} />
            <div style={{ flex: 1 }}>
              <div style={{ color: '#fff', fontSize: 13.5, fontWeight: 600 }}>Tag reading is coming soon</div>
              <div style={{ color: M.faint, fontSize: 11.5, marginTop: 1 }}>
                Brand, size and fabric will fill in automatically
              </div>
            </div>
          </div>
          <Btn variant="glass" size="md" fullWidth disabled title="Coming soon">
            Scan a tag · Coming soon
          </Btn>
        </div>
      </div>
    </AppShell>
  );
}
