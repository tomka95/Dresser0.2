'use client';

/**
 * §6 · F5 — Affiliate redirect interstitial.
 *
 * The /out/{clickId} endpoint is a server 302, but the design shows a brief
 * branded interstitial ("Taking you to {brand}… · Tailor may earn a commission")
 * before the hop. This component is that screen: it renders the brand + a plain-
 * language commission disclosure, then triggers a REAL top-level navigation to
 * /out/{clickId}.
 *
 * MONETIZATION BOUNDARY (security-critical): the interstitial only ever displays
 * the brand name and disclosure. It NEVER receives, builds, or exposes a
 * destination / affiliate URL. The actual destination is resolved server-side by
 * the /out redirect. The client's job here is: mint a click (already done by the
 * caller via mintClick), show the disclosure, then set window.location to the
 * opaque /out/{clickId} path — nothing more.
 */

import { useEffect, useRef } from 'react';
import { API_BASE_URL } from '@/lib/api/base';
import { Mark, M } from '@/components/ds';

/** How long the disclosure is shown before the top-level nav fires (ms). */
const DWELL_MS = 1300;

export interface AffiliateInterstitialProps {
  /** The opaque click id minted by POST /clicks. Only this is used to navigate. */
  clickId: string;
  /** Brand shown in the headline ("Taking you to {brand}…"). Display only. */
  brand: string;
  /** Optional product line under the headline (name · price). Display only. */
  detail?: string;
  /** Cancel the hop (dismiss the interstitial before navigation). */
  onCancel: () => void;
  /**
   * Navigation seam — defaults to a real top-level browser nav to /out/{clickId}.
   * Overridable only for tests; production always uses the server-resolved path.
   */
  navigate?: (clickId: string) => void;
}

function defaultNavigate(clickId: string): void {
  // Top-level navigation (NOT fetch) — /out/{clickId} 302s to the destination,
  // which is resolved entirely server-side. The client never sees the URL.
  window.location.href = `${API_BASE_URL}/out/${clickId}`;
}

export function AffiliateInterstitial({
  clickId,
  brand,
  detail,
  onCancel,
  navigate = defaultNavigate,
}: AffiliateInterstitialProps) {
  const fired = useRef(false);

  useEffect(() => {
    // Respect reduced-motion by not lingering, but always show at least a beat so
    // the disclosure is legible.
    const t = setTimeout(() => {
      if (fired.current) return;
      fired.current = true;
      navigate(clickId);
    }, DWELL_MS);
    return () => clearTimeout(t);
  }, [clickId, navigate]);

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={`Opening ${brand}`}
      className="fixed inset-0 z-[70] mx-auto flex max-w-[430px] flex-col items-center justify-center text-center"
      style={{
        padding: '0 34px',
        background: 'linear-gradient(180deg, rgba(5,10,10,0.94) 0%, rgba(5,10,10,0.98) 100%)',
        backdropFilter: 'blur(8px)',
        WebkitBackdropFilter: 'blur(8px)',
      }}
    >
      <Mark size={110} />
      <div className="text-[20px] font-bold tracking-[-0.4px] text-white" style={{ marginTop: 8 }}>
        Taking you to {brand}…
      </div>
      {detail && (
        <div className="text-[13px]" style={{ color: M.faint, marginTop: 6 }}>
          {detail}
        </div>
      )}

      {/* Indeterminate progress bar — matches the design's sweeping mint bar. */}
      <div
        className="relative overflow-hidden"
        style={{
          width: 180,
          height: 3.5,
          borderRadius: 2,
          background: 'rgba(255,255,255,0.12)',
          marginTop: 22,
        }}
        aria-hidden
      >
        <span
          data-t2-anim
          className="absolute top-0 bottom-0"
          style={{
            width: '40%',
            borderRadius: 2,
            background: 'linear-gradient(90deg, transparent, var(--mint), transparent)',
            animation: 't2-bar 1.4s var(--ease-in-out) infinite',
          }}
        />
      </div>

      {/* Disclosure + cancel — pinned to the lower third like the comp. */}
      <div className="absolute" style={{ bottom: 44, left: 34, right: 34 }}>
        <div className="text-[11px]" style={{ color: M.ghost, lineHeight: 1.6 }}>
          Tailor may earn a commission on this visit.
          <br />
          It never changes prices or what we recommend.
        </div>
        <button
          type="button"
          onClick={() => {
            fired.current = true; // block the pending nav
            onCancel();
          }}
          className="inline-block"
          style={{ marginTop: 12, color: M.faint, fontSize: 12.5 }}
        >
          Cancel
        </button>
      </div>
    </div>
  );
}
