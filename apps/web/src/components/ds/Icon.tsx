import React from 'react';

import { ICONS, type IconName } from './icon-data';

export type { IconName };

interface IconProps extends Omit<React.SVGProps<SVGSVGElement>, 'name'> {
  name: IconName;
  /** Square size in px (width = height). */
  size?: number;
}

/**
 * Design-system icon. Renders the exact glyphs exported from the Tailor design
 * project (coolicons set + the custom Hanger). Strokes/fills use currentColor,
 * so color comes from the parent like any text.
 */
export function Icon({ name, size = 24, ...rest }: IconProps) {
  const icon = ICONS[name];
  return (
    <svg
      width={size}
      height={size}
      viewBox={icon.viewBox}
      fill="currentColor"
      aria-hidden
      focusable={false}
      // Trusted, build-time constant markup from icon-data.ts (no user input).
      dangerouslySetInnerHTML={{ __html: icon.body }}
      {...rest}
    />
  );
}
