import React from 'react';

import { Icon } from './Icon';

interface StylistMarkProps {
  /** Square size in px (width = height). */
  size?: number;
  /**
   * Deprecated. The mark was formerly a threaded needle whose eye was tinted
   * with this color; the mark is now the hanger, which has no eye. Kept in the
   * signature so existing call sites keep compiling — ignored.
   */
  eye?: string;
  style?: React.CSSProperties;
  className?: string;
}

/**
 * The Tailor AI/brand mark — the hanger glyph. This is the single symbol used
 * for every AI accent in the app (the earlier threaded-needle mark was retired
 * in the design refresh; the hanger replaces it everywhere). Rendering the
 * shared `Icon name="Hanger"` here means one edit flips Spark, the nav FAB, the
 * chat stylist medallion, and the outfit "AI styled" accents in lockstep.
 * Color flows from the parent via currentColor.
 */
export function StylistMark({ size = 24, eye, style, className }: StylistMarkProps) {
  void eye; // accepted-but-ignored compat prop (see doc above)
  return <Icon name="Hanger" size={size} style={style} className={className} />;
}
