'use client';

/**
 * useAffiliateOpen — orchestrates the F5 affiliate hop with the branded
 * interstitial in front of the server 302.
 *
 * Flow:
 *   1. open(productId, surface, { brand, detail }) → POST /clicks (mintClick),
 *      which returns the OPAQUE clickId.
 *   2. We stash { clickId, brand, detail } and render <AffiliateInterstitial>,
 *      which shows the commission disclosure, then does a top-level nav to
 *      /out/{clickId}.
 *
 * This replaces a bare openProduct() call: instead of navigating immediately, the
 * user sees the disclosure first. The monetization boundary is preserved — the
 * client only ever holds a productId (before) and a clickId (after); it never
 * receives or constructs the destination URL. See AffiliateInterstitial for the
 * navigation seam.
 */

import { useCallback, useState } from 'react';
import { mintClick } from '@/lib/api/shop';
import { AffiliateInterstitial } from './AffiliateInterstitial';

interface PendingHop {
  clickId: string;
  brand: string;
  detail?: string;
}

interface OpenMeta {
  brand: string;
  detail?: string;
}

export function useAffiliateOpen() {
  const [pending, setPending] = useState<PendingHop | null>(null);
  const [minting, setMinting] = useState(false);

  /**
   * Mint a click then show the interstitial. Throws on mint failure so callers
   * can surface a toast (and the interstitial never appears without a real
   * clickId to navigate to).
   */
  const open = useCallback(
    async (productId: string, surface: string, meta: OpenMeta): Promise<void> => {
      setMinting(true);
      try {
        const clickId = await mintClick(productId, surface);
        setPending({ clickId, brand: meta.brand, detail: meta.detail });
      } finally {
        setMinting(false);
      }
    },
    [],
  );

  const cancel = useCallback(() => setPending(null), []);

  /** Render this in the page tree; it's null until an open() resolves. */
  const interstitial = pending ? (
    <AffiliateInterstitial
      clickId={pending.clickId}
      brand={pending.brand}
      detail={pending.detail}
      onCancel={cancel}
    />
  ) : null;

  return { open, cancel, minting, interstitial, active: !!pending };
}
