import React from 'react';

/**
 * Tailor brand hanger mark — the user-supplied line-art PNG (public/9.png).
 * Wide cream artwork with generous transparent padding, so it's sized by
 * width with height auto.
 */
export function HangerImg({ w = 160, className }: { w?: number; className?: string }) {
  /* eslint-disable-next-line @next/next/no-img-element */
  return <img src="/9.png" alt="" className={className} style={{ width: w, height: 'auto', display: 'block' }} aria-hidden />;
}
